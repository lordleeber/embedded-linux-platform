cmake_minimum_required(VERSION 3.16)
project(embedded_linux_platform CXX)

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
