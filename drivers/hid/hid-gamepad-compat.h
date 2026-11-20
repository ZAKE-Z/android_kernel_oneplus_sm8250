/* SPDX-License-Identifier: GPL-2.0 */
#ifndef HID_GAMEPAD_COMPAT_H
#define HID_GAMEPAD_COMPAT_H

/* Driver-local backports: do not change the ABI of the 4.19 HID core. */
#include <linux/device.h>
#include <linux/hid.h>
#include <linux/mutex.h>
#include <linux/rcupdate.h>
#include <linux/spinlock.h>
#include <linux/workqueue.h>
#include <dt-bindings/leds/common.h>

struct gamepad_guard {
	void *lock;
	unsigned long flags;
	bool once;
};

static inline struct gamepad_guard gamepad_lock_mutex(struct mutex *lock)
{
	struct gamepad_guard guard = { .lock = lock, .once = true };

	mutex_lock(lock);
	return guard;
}

static inline void gamepad_unlock_mutex(struct gamepad_guard *guard)
{
	mutex_unlock(guard->lock);
}

static inline struct gamepad_guard gamepad_lock_spinlock_irqsave(spinlock_t *lock)
{
	struct gamepad_guard guard = { .lock = lock, .once = true };

	spin_lock_irqsave(lock, guard.flags);
	return guard;
}

static inline void gamepad_unlock_spinlock_irqsave(struct gamepad_guard *guard)
{
	spin_unlock_irqrestore((spinlock_t *)guard->lock, guard->flags);
}

static inline struct gamepad_guard gamepad_lock_rcu(void)
{
	struct gamepad_guard guard = { .once = true };

	rcu_read_lock();
	return guard;
}

static inline void gamepad_unlock_rcu(struct gamepad_guard *guard)
{
	rcu_read_unlock();
}

/* cleanup runs on normal exit, return, break and goto, not just fallthrough. */
#define __gamepad_guard(type, id) \
	struct gamepad_guard __maybe_unused __attribute__((__cleanup__(gamepad_unlock_##type))) \
		__PASTE(gamepad_guard_, id) = gamepad_lock_##type
#define guard(type) __gamepad_guard(type, __COUNTER__)
#define scoped_guard(type, args...) \
	for (struct gamepad_guard __attribute__((__cleanup__(gamepad_unlock_##type))) \
		gamepad_scope = gamepad_lock_##type(args); \
		gamepad_scope.once; gamepad_scope.once = false)

#define timer_container_of(var, timer, member) from_timer(var, timer, member)

#ifndef hid_warn_ratelimited
#define hid_warn_ratelimited(hdev, fmt, args...) \
	dev_warn_ratelimited(&(hdev)->dev, fmt, ##args)
#endif

static inline void gamepad_cancel_delayed_work(void *data)
{
	cancel_delayed_work_sync(data);
}

static inline int gamepad_devm_delayed_work_autocancel(struct device *dev,
		struct delayed_work *work, work_func_t fn)
{
	INIT_DELAYED_WORK(work, fn);
	return devm_add_action_or_reset(dev, gamepad_cancel_delayed_work, work);
}

#endif /* HID_GAMEPAD_COMPAT_H */
