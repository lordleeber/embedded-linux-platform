// SPDX-License-Identifier: GPL-2.0
/*
 * edge_button - Step 5-b: a DT-described push button whose presses wake a
 * blocked read() on /dev/edge_button.
 *
 *   button edge -> IRQ handler (counts, re-arms the debounce timer)
 *               -> debounce work, 20 ms after the last edge (reads the level,
 *                  queues an event if the state changed)
 *               -> wake_up_interruptible() -> read() returns one event
 *
 * Event semantics (struct edge_button_event in include/edge_button.h):
 * - one "pressed" and one "released" per press, however long it is held;
 *   bounces shorter than the debounce time are merged, a press shorter than it
 *   may be missed;
 * - seq counts every debounced state change since load, so a gap in seq means
 *   events were lost: the queue holds 16, a full queue drops the new event and
 *   bumps "dropped";
 * - one reader at a time (a second open() gets EBUSY); open() empties the
 *   queue and nothing is queued while the device is closed.
 */
#include <linux/atomic.h>
#include <linux/fs.h>
#include <linux/gpio/consumer.h>
#include <linux/interrupt.h>
#include <linux/kernel.h>
#include <linux/kfifo.h>
#include <linux/miscdevice.h>
#include <linux/mod_devicetable.h>
#include <linux/module.h>
#include <linux/platform_device.h>
#include <linux/spinlock.h>
#include <linux/timekeeping.h>
#include <linux/uaccess.h>
#include <linux/wait.h>
#include <linux/workqueue.h>

#include "edge_button.h"

#define EDGE_BUTTON_DEBOUNCE_MS	20
#define EDGE_BUTTON_OPEN	0	/* bit in flags */

struct edge_button {
	struct gpio_desc *gpio;
	struct miscdevice misc;
	struct delayed_work work;
	wait_queue_head_t wq;
	spinlock_t lock;	/* fifo, last, seq, dropped */
	DECLARE_KFIFO(fifo, struct edge_button_event, 16);
	int last;		/* last debounced state, 1 = pressed */
	u32 seq;
	u32 dropped;
	atomic_t irq_count;	/* raw edges, bounces included */
	unsigned long flags;
};

static struct edge_button *to_edge_button(struct file *file)
{
	return container_of(file->private_data, struct edge_button, misc);
}

static irqreturn_t edge_button_irq(int irq, void *data)
{
	struct edge_button *eb = data;

	/*
	 * Hard IRQ context: no sleeping, no GPIO read (the _cansleep accessor may
	 * sleep). Every edge pushes the deadline back, so the work runs once the
	 * line has been quiet for the debounce time.
	 */
	atomic_inc(&eb->irq_count);
	mod_delayed_work(system_wq, &eb->work,
			 msecs_to_jiffies(EDGE_BUTTON_DEBOUNCE_MS));
	return IRQ_HANDLED;
}

static void edge_button_work(struct work_struct *work)
{
	struct edge_button *eb = container_of(to_delayed_work(work),
					      struct edge_button, work);
	struct edge_button_event ev;
	int val;

	val = gpiod_get_value_cansleep(eb->gpio);	/* logical: DT says active-low */
	if (val < 0)
		return;

	spin_lock(&eb->lock);
	if (val == eb->last) {		/* bounced back to where it was */
		spin_unlock(&eb->lock);
		return;
	}
	eb->last = val;
	ev.timestamp_ns = ktime_get_ns();
	ev.seq = ++eb->seq;
	ev.pressed = val;
	if (test_bit(EDGE_BUTTON_OPEN, &eb->flags) && !kfifo_put(&eb->fifo, ev))
		eb->dropped++;
	spin_unlock(&eb->lock);

	wake_up_interruptible(&eb->wq);
}

static int edge_button_open(struct inode *inode, struct file *file)
{
	struct edge_button *eb = to_edge_button(file);

	if (test_and_set_bit(EDGE_BUTTON_OPEN, &eb->flags))
		return -EBUSY;
	spin_lock(&eb->lock);
	kfifo_reset(&eb->fifo);
	spin_unlock(&eb->lock);
	return 0;
}

static int edge_button_release(struct inode *inode, struct file *file)
{
	clear_bit(EDGE_BUTTON_OPEN, &to_edge_button(file)->flags);
	return 0;
}

/* Returns exactly one event per call; blocks until there is one. */
static ssize_t edge_button_read(struct file *file, char __user *ubuf,
				size_t count, loff_t *ppos)
{
	struct edge_button *eb = to_edge_button(file);
	struct edge_button_event ev;
	int got, ret;

	if (count < sizeof(ev))
		return -EINVAL;

	for (;;) {
		spin_lock(&eb->lock);
		got = kfifo_get(&eb->fifo, &ev);
		spin_unlock(&eb->lock);
		if (got)
			break;
		if (file->f_flags & O_NONBLOCK)
			return -EAGAIN;
		/* Sleeps (no CPU) until the work queues an event or a signal arrives. */
		ret = wait_event_interruptible(eb->wq, !kfifo_is_empty(&eb->fifo));
		if (ret)
			return ret;
	}

	/* The event has left the queue: a bad buffer loses it (seq shows the gap). */
	if (copy_to_user(ubuf, &ev, sizeof(ev)))
		return -EFAULT;
	return sizeof(ev);
}

static const struct file_operations edge_button_fops = {
	.owner		= THIS_MODULE,
	.open		= edge_button_open,
	.release	= edge_button_release,
	.read		= edge_button_read,
	.llseek		= no_llseek,
};

static ssize_t irq_count_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct edge_button *eb = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%d\n", atomic_read(&eb->irq_count));
}
static DEVICE_ATTR_RO(irq_count);

static ssize_t event_count_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct edge_button *eb = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", READ_ONCE(eb->seq));
}
static DEVICE_ATTR_RO(event_count);

static ssize_t dropped_show(struct device *dev, struct device_attribute *attr, char *buf)
{
	struct edge_button *eb = dev_get_drvdata(dev);

	return sysfs_emit(buf, "%u\n", READ_ONCE(eb->dropped));
}
static DEVICE_ATTR_RO(dropped);

static struct attribute *edge_button_attrs[] = {
	&dev_attr_irq_count.attr,
	&dev_attr_event_count.attr,
	&dev_attr_dropped.attr,
	NULL
};
ATTRIBUTE_GROUPS(edge_button);

static void edge_button_cancel_work(void *data)
{
	struct edge_button *eb = data;

	cancel_delayed_work_sync(&eb->work);
}

static int edge_button_probe(struct platform_device *pdev)
{
	struct device *dev = &pdev->dev;
	struct edge_button *eb;
	int irq, ret;

	eb = devm_kzalloc(dev, sizeof(*eb), GFP_KERNEL);
	if (!eb)
		return -ENOMEM;

	/* Looks up "button-gpios"; the active-low flag makes 1 mean pressed. */
	eb->gpio = devm_gpiod_get(dev, "button", GPIOD_IN);
	if (IS_ERR(eb->gpio))
		return dev_err_probe(dev, PTR_ERR(eb->gpio), "cannot get button gpio\n");

	spin_lock_init(&eb->lock);
	init_waitqueue_head(&eb->wq);
	INIT_KFIFO(eb->fifo);
	INIT_DELAYED_WORK(&eb->work, edge_button_work);
	/*
	 * devm undoes in reverse order: registered before the IRQ, so on removal
	 * the IRQ is freed first (no new work) and then pending work is cancelled.
	 */
	ret = devm_add_action_or_reset(dev, edge_button_cancel_work, eb);
	if (ret)
		return ret;

	eb->last = gpiod_get_value_cansleep(eb->gpio);
	if (eb->last < 0)
		return dev_err_probe(dev, eb->last, "cannot read button gpio\n");

	irq = gpiod_to_irq(eb->gpio);
	if (irq < 0)
		return dev_err_probe(dev, irq, "button gpio has no irq\n");
	ret = devm_request_irq(dev, irq, edge_button_irq,
			       IRQF_TRIGGER_RISING | IRQF_TRIGGER_FALLING,
			       "edge_button", eb);
	if (ret)
		return dev_err_probe(dev, ret, "cannot request irq %d\n", irq);

	platform_set_drvdata(pdev, eb);
	eb->misc.minor = MISC_DYNAMIC_MINOR;
	eb->misc.name = "edge_button";
	eb->misc.fops = &edge_button_fops;
	eb->misc.parent = dev;
	eb->misc.mode = 0444;
	ret = misc_register(&eb->misc);
	if (ret)
		return ret;

	dev_info(dev, "probed: button gpio acquired (irq %d, %s)\n",
		 irq, eb->last ? "pressed" : "released");
	return 0;
}

static int edge_button_remove(struct platform_device *pdev)
{
	struct edge_button *eb = platform_get_drvdata(pdev);

	/* No reader can be blocked here: an open file holds the module (.owner). */
	misc_deregister(&eb->misc);
	dev_info(&pdev->dev, "removed: %d irqs, %u events, %u dropped\n",
		 atomic_read(&eb->irq_count), eb->seq, eb->dropped);
	return 0;
}

static const struct of_device_id edge_button_of_match[] = {
	{ .compatible = "edge,gpio-button" },
	{ }
};
MODULE_DEVICE_TABLE(of, edge_button_of_match);

static struct platform_driver edge_button_driver = {
	.probe	= edge_button_probe,
	.remove	= edge_button_remove,
	.driver	= {
		.name = "edge_button",
		.of_match_table = edge_button_of_match,
		.dev_groups = edge_button_groups,
		/* Same reason as edge_gpio: unbinding would free eb under an open file. */
		.suppress_bind_attrs = true,
	},
};
module_platform_driver(edge_button_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Step 5-b: DT-described button, IRQ + debounce + blocking read");
