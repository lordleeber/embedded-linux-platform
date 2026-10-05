// SPDX-License-Identifier: GPL-2.0
/*
 * edge_test - minimal character device backed by a 256-byte kernel buffer.
 *
 * write() copies user data into the buffer at the file position, read()
 * returns what has been stored. Opening for write with O_TRUNC clears it,
 * so `echo hello > /dev/edge_test` followed by `cat /dev/edge_test`
 * behaves like a tiny file. Writes past the end are cut short; once the
 * buffer is full, further writes fail with -ENOSPC.
 */
#include <linux/cdev.h>
#include <linux/device.h>
#include <linux/fs.h>
#include <linux/module.h>
#include <linux/mutex.h>
#include <linux/string.h>
#include <linux/uaccess.h>

#define EDGE_TEST_NAME		"edge_test"
#define EDGE_TEST_BUF_SIZE	256

static dev_t edge_test_devt;
static struct cdev edge_test_cdev;
static struct class *edge_test_class;
static struct device *edge_test_device;

static DEFINE_MUTEX(edge_test_lock);	/* protects buf and data_len */
static char edge_test_buf[EDGE_TEST_BUF_SIZE];
static size_t edge_test_data_len;

static int edge_test_open(struct inode *inode, struct file *file)
{
	if ((file->f_mode & FMODE_WRITE) && (file->f_flags & O_TRUNC)) {
		mutex_lock(&edge_test_lock);
		edge_test_data_len = 0;
		mutex_unlock(&edge_test_lock);
	}
	pr_debug("edge_test: open (flags 0x%x)\n", file->f_flags);
	return 0;
}

static int edge_test_release(struct inode *inode, struct file *file)
{
	pr_debug("edge_test: release\n");
	return 0;
}

static ssize_t edge_test_read(struct file *file, char __user *ubuf,
			      size_t count, loff_t *ppos)
{
	ssize_t ret;

	mutex_lock(&edge_test_lock);
	if (*ppos >= edge_test_data_len) {
		ret = 0;	/* EOF */
		goto out;
	}
	count = min_t(size_t, count, edge_test_data_len - *ppos);
	if (copy_to_user(ubuf, edge_test_buf + *ppos, count)) {
		ret = -EFAULT;
		goto out;
	}
	*ppos += count;
	ret = count;
out:
	mutex_unlock(&edge_test_lock);
	return ret;
}

static ssize_t edge_test_write(struct file *file, const char __user *ubuf,
			       size_t count, loff_t *ppos)
{
	char tmp[EDGE_TEST_BUF_SIZE];
	ssize_t ret;

	if (count == 0)
		return 0;

	mutex_lock(&edge_test_lock);
	if (*ppos >= EDGE_TEST_BUF_SIZE) {
		ret = -ENOSPC;
		goto out;
	}
	count = min_t(size_t, count, EDGE_TEST_BUF_SIZE - *ppos);
	/*
	 * copy_from_user() zero-fills the destination bytes it could not
	 * copy, so copy into tmp first; a faulting write must not clobber
	 * what is already stored.
	 */
	if (copy_from_user(tmp, ubuf, count)) {
		ret = -EFAULT;
		goto out;
	}
	memcpy(edge_test_buf + *ppos, tmp, count);
	*ppos += count;
	edge_test_data_len = max_t(size_t, edge_test_data_len, *ppos);
	ret = count;
out:
	mutex_unlock(&edge_test_lock);
	return ret;
}

static const struct file_operations edge_test_fops = {
	.owner		= THIS_MODULE,
	.open		= edge_test_open,
	.release	= edge_test_release,
	.read		= edge_test_read,
	.write		= edge_test_write,
};

/* Make the devtmpfs node 0666 so the acceptance commands work without sudo. */
static char *edge_test_devnode(struct device *dev, umode_t *mode)
{
	if (mode)
		*mode = 0666;
	return NULL;
}

static int __init edge_test_init(void)
{
	int ret;

	ret = alloc_chrdev_region(&edge_test_devt, 0, 1, EDGE_TEST_NAME);
	if (ret)
		return ret;

	cdev_init(&edge_test_cdev, &edge_test_fops);
	edge_test_cdev.owner = THIS_MODULE;
	ret = cdev_add(&edge_test_cdev, edge_test_devt, 1);
	if (ret)
		goto err_region;

	edge_test_class = class_create(THIS_MODULE, EDGE_TEST_NAME);
	if (IS_ERR(edge_test_class)) {
		ret = PTR_ERR(edge_test_class);
		goto err_cdev;
	}
	edge_test_class->devnode = edge_test_devnode;

	edge_test_device = device_create(edge_test_class, NULL, edge_test_devt,
					 NULL, EDGE_TEST_NAME);
	if (IS_ERR(edge_test_device)) {
		ret = PTR_ERR(edge_test_device);
		goto err_class;
	}

	pr_info("edge_test: registered /dev/%s (major %d, minor %d)\n",
		EDGE_TEST_NAME, MAJOR(edge_test_devt), MINOR(edge_test_devt));
	return 0;

err_class:
	class_destroy(edge_test_class);
err_cdev:
	cdev_del(&edge_test_cdev);
err_region:
	unregister_chrdev_region(edge_test_devt, 1);
	return ret;
}

static void __exit edge_test_exit(void)
{
	device_destroy(edge_test_class, edge_test_devt);
	class_destroy(edge_test_class);
	cdev_del(&edge_test_cdev);
	unregister_chrdev_region(edge_test_devt, 1);
	pr_info("edge_test: unregistered\n");
}

module_init(edge_test_init);
module_exit(edge_test_exit);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("Minimal character device with a 256-byte buffer");
MODULE_AUTHOR("embedded-linux-platform");
