/* SPDX-License-Identifier: GPL-2.0 */
/* Privileged UHID relay. BLE/GATT stays in the Android application. */
#include <errno.h>
#include <fcntl.h>
#include <linux/input.h>
#include <linux/uhid.h>
#include <poll.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

static const unsigned char descriptor[] = {
	0x06, 0x00, 0xff, 0x09, 0x01, 0xa1, 0x01,
	0x85, 0x01, 0x15, 0x00, 0x26, 0xff, 0x00,
	0x75, 0x08, 0x95, 0x82, 0x09, 0x01, 0x81, 0x02,
	0x09, 0x02, 0x91, 0x02, 0xc0,
};

static int send_event(int fd, struct uhid_event *ev)
{
	ssize_t n;

	do { n = write(fd, ev, sizeof(*ev)); } while (n < 0 && errno == EINTR);
	return n == sizeof(*ev) ? 0 : -1;
}

static int hexval(char c)
{
	if (c >= '0' && c <= '9') return c - '0';
	if (c >= 'a' && c <= 'f') return c - 'a' + 10;
	if (c >= 'A' && c <= 'F') return c - 'A' + 10;
	return -1;
}

static int parse_input(int fd, char *line)
{
	struct uhid_event ev = { .type = UHID_INPUT2 };
	char *end;
	unsigned long handle;
	size_t len, i;

	if (strncmp(line, "I ", 2)) return -1;
	handle = strtoul(line + 2, &end, 16);
	if (*end != ' ' || handle > 0xffff) return -1;
	end++;
	len = strcspn(end, "\r\n");
	if (len % 2 || len > 256 || !len) return -1;
	ev.u.input2.data[0] = 1;
	ev.u.input2.data[1] = handle & 0xff;
	ev.u.input2.data[2] = handle >> 8;
	for (i = 0; i < len / 2; i++) {
		int hi = hexval(end[i * 2]), lo = hexval(end[i * 2 + 1]);
		if (hi < 0 || lo < 0) return -1;
		ev.u.input2.data[i + 3] = (hi << 4) | lo;
	}
	ev.u.input2.size = len / 2 + 3;
	return send_event(fd, &ev);
}

int main(int argc, char **argv)
{
	struct uhid_event ev = { .type = UHID_CREATE2 };
	struct pollfd pfd[2] = { { .fd = STDIN_FILENO, .events = POLLIN }, { .events = POLLIN } };
	char line[512];
	size_t used = 0;
	unsigned long product;
	char *end;
	bool ready = false;
	int fd, status = 1;

	if (argc != 3) { fprintf(stderr, "usage: ns2relay PRODUCT_HEX MAC\n"); return 2; }
	product = strtoul(argv[1], &end, 16);
	if (*end || (product != 0x2066 && product != 0x2067 && product != 0x2069 && product != 0x2073) ||
	    strlen(argv[2]) != 17 || strspn(argv[2], "0123456789ABCDEFabcdef:") != 17) return 2;
	fd = open("/dev/uhid", O_RDWR | O_CLOEXEC);
	if (fd < 0) { perror("open /dev/uhid"); return 1; }
	pfd[1].fd = fd;
	snprintf((char *)ev.u.create2.name, sizeof(ev.u.create2.name), "Switch 2 BLE Bridge %04lx", product);
	snprintf((char *)ev.u.create2.phys, sizeof(ev.u.create2.phys), "ns2-gatt-v1/%s", argv[2]);
	snprintf((char *)ev.u.create2.uniq, sizeof(ev.u.create2.uniq), "%s", argv[2]);
	ev.u.create2.bus = BUS_BLUETOOTH;
	ev.u.create2.vendor = 0x057e;
	ev.u.create2.product = product;
	ev.u.create2.version = 0x8001;
	ev.u.create2.rd_size = sizeof(descriptor);
	memcpy(ev.u.create2.rd_data, descriptor, sizeof(descriptor));
	if (send_event(fd, &ev)) { perror("UHID_CREATE2"); goto out; }
	setvbuf(stdout, NULL, _IOLBF, 0);
	while (1) {
		int n = poll(pfd, 2, -1);
		if (n < 0) { if (errno == EINTR) continue; break; }
		if (pfd[1].revents & POLLIN) {
			ssize_t got = read(fd, &ev, sizeof(ev));
			if (got <= 0) break;
			if (ev.type == UHID_OPEN && !ready) {
				ready = true;
				puts("READY");
			} else if (ev.type == UHID_OUTPUT) {
				unsigned int i;
				if (ev.u.output.size < 2 || ev.u.output.size > 66) break;
				printf("O %04x ", ev.u.output.data[0] | (ev.u.output.data[1] << 8));
				for (i = 2; i < ev.u.output.size; i++) printf("%02x", ev.u.output.data[i]);
				putchar('\n');
			} else if (ev.type == UHID_STOP) break;
		}
		if (pfd[0].revents & POLLIN) {
			char buf[256];
			ssize_t got = read(STDIN_FILENO, buf, sizeof(buf));
			ssize_t i;
			if (got <= 0) { status = 0; break; }
			for (i = 0; i < got; i++) {
				if (used == sizeof(line) - 1) goto out;
				line[used++] = buf[i];
				if (buf[i] == '\n') {
					line[used] = 0;
					if (parse_input(fd, line)) { fprintf(stderr, "invalid input or UHID write\n"); goto out; }
					used = 0;
				}
			}
		}
		if (pfd[0].revents & (POLLHUP | POLLERR)) { status = 0; break; }
		if (pfd[1].revents & (POLLHUP | POLLERR)) break;
	}
out:
	memset(&ev, 0, sizeof(ev));
	ev.type = UHID_DESTROY;
	send_event(fd, &ev);
	close(fd);
	return status;
}
