cmake_minimum_required(VERSION 3.16)
project(embedded_linux_platform C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE RelWithDebInfo)
endif()
add_compile_options(-Wall -Wextra -Werror)

# Step 3: userspace side of the edge_test ioctl interface.
add_executable(edge_test_cli apps/edge_test_cli.cpp)
target_include_directories(edge_test_cli PRIVATE include)

add_executable(test_edge_device tests/test_edge_device.cpp)
target_include_directories(test_edge_device PRIVATE include)

# Step 4-a: userspace GPIO through the kernel's GPIO v2 character-device uAPI (fixed: pin 29).
add_executable(edge_gpio_blink apps/edge_gpio_blink.cpp)

# Step 5-b: blocking read() of button events from /dev/edge_button (kernel/edge_button).
add_executable(edge_button_wait apps/edge_button_wait.cpp)
target_include_directories(edge_button_wait PRIVATE include)

# Step 5-a: the same button through gpiolib-cdev edge events (GPIO v2 uAPI, no driver).
add_executable(edge_gpio_button apps/edge_gpio_button.cpp)

# Step 6-b: INA219 registers through i2c-dev (I2C_RDWR), no Python library, no driver.
add_executable(ina219_raw tools/ina219_raw.cpp)
add_executable(test_ina219_decode tests/test_ina219_decode.cpp)

# Step 7: the kernel driver's arithmetic (include/edge_ina219_conv.h) against Step 6-b's decoder.
add_executable(test_edge_ina219_conv tests/test_edge_ina219_conv.cpp)

# Step 9: SSD1306 OLED from userspace (i2c-dev, I2C_RDWR); protocol bytes in tools/ssd1306.h.
add_executable(oled_probe tools/oled_probe.cpp)
add_executable(test_ssd1306 tests/test_ssd1306.cpp)

# Step 10-a: userspace side of edge_oled.ko (/dev/edge_oled); the driver's SSD1306 bytes vs Step 9's.
add_executable(edge_oled_ctl apps/edge_oled_ctl.cpp)
target_include_directories(edge_oled_ctl PRIVATE include tools)
add_executable(test_edge_oled_proto tests/test_edge_oled_proto.cpp)
target_include_directories(test_edge_oled_proto PRIVATE include)

# Step 10-b: text into the frame (apps/oled_text.h, 5x7 font), drawn by edge_oled_ctl text / font.
add_executable(test_oled_text tests/test_oled_text.cpp)

# Step 10-c: INA219 hwmon values on the OLED (userspace only; policy in apps/telemetry.h).
add_executable(telemetry_display apps/telemetry_display.cpp)
target_include_directories(telemetry_display PRIVATE include)
add_executable(test_telemetry tests/test_telemetry.cpp)

# Step 11: the STM32F103 firmware's I2C register protocol (pure C, no SPL) on the host.
add_executable(test_i2c_target tests/test_i2c_target.cpp firmware/stm32f103/Core/Src/i2c_target.c)
target_include_directories(test_i2c_target PRIVATE firmware/stm32f103/Core/Inc)
# Step 12-b: the button debounce (pure C, called from SysTick on the board).
add_executable(test_debounce tests/test_debounce.cpp firmware/stm32f103/Core/Src/debounce.c)
target_include_directories(test_debounce PRIVATE firmware/stm32f103/Core/Inc)
