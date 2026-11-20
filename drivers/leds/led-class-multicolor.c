// SPDX-License-Identifier: GPL-2.0
// LED Multicolor class interface
// Copyright (C) 2019-20 Texas Instruments Incorporated - http://www.ti.com/
// Author: Dan Murphy <dmurphy@ti.com>
// Adapted from Linux v5.10 to the 4.19 LED registration API.

#include <linux/ctype.h>
#include <linux/device.h>
#include <linux/led-class-multicolor.h>
#include <linux/module.h>
#include <linux/slab.h>

static const char * const gamepad_led_colors[LED_COLOR_ID_MAX] = {
	"white", "red", "green", "blue", "amber", "violet", "yellow",
	"ir", "multicolor", "rgb",
};

int led_mc_calc_color_components(struct led_classdev_mc *mcled_cdev,
				enum led_brightness brightness)
{
	struct led_classdev *led_cdev = &mcled_cdev->led_cdev;
	int i;

	if (!led_cdev->max_brightness)
		return -EINVAL;
	for (i = 0; i < mcled_cdev->num_colors; i++)
		mcled_cdev->subled_info[i].brightness =
			brightness * mcled_cdev->subled_info[i].intensity /
			led_cdev->max_brightness;
	return 0;
}
EXPORT_SYMBOL_GPL(led_mc_calc_color_components);

static ssize_t multi_intensity_store(struct device *dev,
		struct device_attribute *attr, const char *buf, size_t size)
{
	struct led_classdev *led_cdev = dev_get_drvdata(dev);
	struct led_classdev_mc *mcled_cdev = lcdev_to_mccdev(led_cdev);
	unsigned int values[LED_COLOR_ID_MAX];
	int nrchars, offset = 0, i;
	ssize_t ret = -EINVAL;

	mutex_lock(&led_cdev->led_access);
	for (i = 0; i < mcled_cdev->num_colors; i++) {
		if (offset >= size ||
		    sscanf(buf + offset, "%u%n", &values[i], &nrchars) != 1 ||
		    values[i] > led_cdev->max_brightness)
			goto out;
		offset += nrchars;
	}
	while (offset < size && isspace(buf[offset]))
		offset++;
	if (offset != size)
		goto out;
	for (i = 0; i < mcled_cdev->num_colors; i++)
		mcled_cdev->subled_info[i].intensity = values[i];
	led_set_brightness(led_cdev, led_cdev->brightness);
	ret = size;
out:
	mutex_unlock(&led_cdev->led_access);
	return ret;
}

static ssize_t multi_intensity_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	struct led_classdev *led_cdev = dev_get_drvdata(dev);
	struct led_classdev_mc *mcled_cdev = lcdev_to_mccdev(led_cdev);
	int len = 0, i;

	mutex_lock(&led_cdev->led_access);
	for (i = 0; i < mcled_cdev->num_colors; i++)
		len += scnprintf(buf + len, PAGE_SIZE - len, "%u%c",
			mcled_cdev->subled_info[i].intensity,
			i == mcled_cdev->num_colors - 1 ? '\n' : ' ');
	mutex_unlock(&led_cdev->led_access);
	return len;
}
static DEVICE_ATTR_RW(multi_intensity);

static ssize_t multi_index_show(struct device *dev,
		struct device_attribute *attr, char *buf)
{
	struct led_classdev *led_cdev = dev_get_drvdata(dev);
	struct led_classdev_mc *mcled_cdev = lcdev_to_mccdev(led_cdev);
	int len = 0, i;

	for (i = 0; i < mcled_cdev->num_colors; i++)
		len += scnprintf(buf + len, PAGE_SIZE - len, "%s%c",
			gamepad_led_colors[mcled_cdev->subled_info[i].color_index],
			i == mcled_cdev->num_colors - 1 ? '\n' : ' ');
	return len;
}
static DEVICE_ATTR_RO(multi_index);

static struct attribute *led_multicolor_attrs[] = {
	&dev_attr_multi_intensity.attr,
	&dev_attr_multi_index.attr,
	NULL,
};
ATTRIBUTE_GROUPS(led_multicolor);

int led_classdev_multicolor_register_ext(struct device *parent,
		struct led_classdev_mc *mcled_cdev, struct led_init_data *init_data)
{
	int i;

	/* 4.19 has no led_init_data; the HID drivers use explicit LED names. */
	if (init_data)
		return -EOPNOTSUPP;
	if (!mcled_cdev || !mcled_cdev->subled_info ||
	    !mcled_cdev->num_colors || mcled_cdev->num_colors > LED_COLOR_ID_MAX)
		return -EINVAL;
	for (i = 0; i < mcled_cdev->num_colors; i++)
		if (mcled_cdev->subled_info[i].color_index >= LED_COLOR_ID_MAX)
			return -EINVAL;
	mcled_cdev->led_cdev.groups = led_multicolor_groups;
	return led_classdev_register(parent, &mcled_cdev->led_cdev);
}
EXPORT_SYMBOL_GPL(led_classdev_multicolor_register_ext);

void led_classdev_multicolor_unregister(struct led_classdev_mc *mcled_cdev)
{
	if (mcled_cdev)
		led_classdev_unregister(&mcled_cdev->led_cdev);
}
EXPORT_SYMBOL_GPL(led_classdev_multicolor_unregister);

static void devm_led_classdev_multicolor_release(struct device *dev, void *res)
{
	led_classdev_multicolor_unregister(*(struct led_classdev_mc **)res);
}

int devm_led_classdev_multicolor_register_ext(struct device *parent,
		struct led_classdev_mc *mcled_cdev, struct led_init_data *init_data)
{
	struct led_classdev_mc **dr;
	int ret;

	dr = devres_alloc(devm_led_classdev_multicolor_release,
			  sizeof(*dr), GFP_KERNEL);
	if (!dr)
		return -ENOMEM;
	ret = led_classdev_multicolor_register_ext(parent, mcled_cdev, init_data);
	if (ret) {
		devres_free(dr);
		return ret;
	}
	*dr = mcled_cdev;
	devres_add(parent, dr);
	return 0;
}
EXPORT_SYMBOL_GPL(devm_led_classdev_multicolor_register_ext);

static int devm_led_classdev_multicolor_match(struct device *dev,
		void *res, void *data)
{
	struct led_classdev_mc **p = res;

	if (WARN_ON(!p || !*p))
		return 0;
	return *p == data;
}

void devm_led_classdev_multicolor_unregister(struct device *dev,
		struct led_classdev_mc *mcled_cdev)
{
	WARN_ON(devres_release(dev, devm_led_classdev_multicolor_release,
			      devm_led_classdev_multicolor_match, mcled_cdev));
}
EXPORT_SYMBOL_GPL(devm_led_classdev_multicolor_unregister);

MODULE_AUTHOR("Dan Murphy <dmurphy@ti.com>");
MODULE_DESCRIPTION("Multicolor LED class interface (4.19 backport)");
MODULE_LICENSE("GPL v2");
