/* SPDX-License-Identifier: GPL-2.0 */
#ifndef HID_GAMEPAD_PROTOCOL_H
#define HID_GAMEPAD_PROTOCOL_H

/* Decoding only, no firmware writes. Offsets follow ndeadly's report 0x05
 * documentation and the MIT-licensed trevlars BLE decoder. USB/UHID carries
 * a leading report ID that is absent from the BLE characteristic value.
 * Decoder reference: Copyright (c) 2026 trevlars (MIT); notice preserved
 * in tools/gamepad/LICENSE.trevlars.
 */
struct gamepad_ns2_sample {
	u32 timestamp;
	s16 accel[3];
	s16 gyro[3];
	s16 magnetometer[3];
	s16 temperature;
	u16 voltage_mv;
	u16 mouse_x;
	u16 mouse_y;
};

static inline int gamepad_ns2_decode(const u8 *data, size_t size,
		struct gamepad_ns2_sample *sample)
{
	int i;

	if (!data || !sample || size < 64 || data[0] != 0x05)
		return -EINVAL;
	sample->timestamp = get_unaligned_le32(data + 0x2b);
	sample->temperature = (s16)get_unaligned_le16(data + 0x2f);
	sample->voltage_mv = get_unaligned_le16(data + 0x20);
	sample->mouse_x = get_unaligned_le16(data + 0x11);
	sample->mouse_y = get_unaligned_le16(data + 0x13);
	for (i = 0; i < 3; i++) {
		sample->accel[i] = (s16)get_unaligned_le16(data + 0x31 + i * 2);
		sample->gyro[i] = (s16)get_unaligned_le16(data + 0x37 + i * 2);
		sample->magnetometer[i] = (s16)get_unaligned_le16(data + 0x1a + i * 2);
	}
	return 0;
}

static inline s16 gamepad_ns2_mouse_delta(u16 position, u16 previous)
{
	return (s16)(position - previous);
}

#endif /* HID_GAMEPAD_PROTOCOL_H */
