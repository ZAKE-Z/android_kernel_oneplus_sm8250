/* SPDX-License-Identifier: GPL-2.0 */
package org.oppo.gamepad.ns2bridge;

import android.Manifest;
import android.app.Activity;
import android.bluetooth.*;
import android.bluetooth.le.*;
import android.content.pm.PackageManager;
import android.os.*;
import android.widget.*;
import java.io.*;
import java.util.*;

/** Experimental one-controller GATT transport. Requires root and this kernel. */
public final class MainActivity extends Activity {
    private static final UUID SERVICE = UUID.fromString("ab7de9be-89fe-49ad-828f-118f09df7fd0");
    private static final UUID INPUT = UUID.fromString("ab7de9be-89fe-49ad-828f-118f09df7fd2");
    private static final UUID COMMAND = UUID.fromString("649d4ac9-8eb7-4e6c-af44-1ea54fe5f005");
    private static final UUID ACK = UUID.fromString("c765a961-d9d8-4d36-a20a-5315b111836a");
    private static final UUID CCC = UUID.fromString("00002902-0000-1000-8000-00805f9b34fb");
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final ArrayDeque<Runnable> operations = new ArrayDeque<>();
    private BluetoothAdapter adapter;
    private BluetoothGatt gatt;
    private BluetoothGattCharacteristic command, haptic;
    private TextView log;
    private LinearLayout devices;
    private java.lang.Process relay;
    private BufferedWriter relayIn;
    private boolean busy, notificationsReady, closing;
    private int product, generation;
    private String address;
    private final Set<String> discovered = new HashSet<>();
    private final Runnable timeout = () -> fail("GATT operation timed out; disconnected, no silent retry");

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        getWindow().addFlags(android.view.WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        LinearLayout page = new LinearLayout(this);
        page.setOrientation(LinearLayout.VERTICAL);
        TextView warning = new TextView(this);
        warning.setText("Experimental / 未经真机验证\nNeeds the extended kernel + explicit root approval. Hold SYNC before scanning. One controller; keep this screen open. Do not grant root unless you trust this test build.");
        page.addView(warning);
        Button scan = new Button(this); scan.setText("Scan / 扫描");
        scan.setOnClickListener(v -> scan()); page.addView(scan);
        Button stop = new Button(this); stop.setText("Disconnect / 断开");
        stop.setOnClickListener(v -> disconnect()); page.addView(stop);
        Button status = new Button(this); status.setText("Kernel status / 内核初始化状态");
        status.setOnClickListener(v -> kernelStatus()); page.addView(status);
        devices = new LinearLayout(this); devices.setOrientation(LinearLayout.VERTICAL); page.addView(devices);
        log = new TextView(this);
        ScrollView scroll = new ScrollView(this); scroll.addView(log); page.addView(scroll);
        setContentView(page);
        BluetoothManager manager = (BluetoothManager)getSystemService(BLUETOOTH_SERVICE);
        adapter = manager.getAdapter();
        if (Build.VERSION.SDK_INT >= 31)
            requestPermissions(new String[]{Manifest.permission.BLUETOOTH_SCAN, Manifest.permission.BLUETOOTH_CONNECT}, 1);
        else requestPermissions(new String[]{Manifest.permission.ACCESS_FINE_LOCATION}, 1);
    }

    private void say(String text) {
        handler.post(() -> { if (log.length() > 12000) log.setText(""); log.append(text + "\n"); });
    }
    private void fail(String text) { say(text); handler.post(this::disconnect); }
    private boolean permitted() {
        return Build.VERSION.SDK_INT < 31 ||
            (checkSelfPermission(Manifest.permission.BLUETOOTH_SCAN) == PackageManager.PERMISSION_GRANTED &&
             checkSelfPermission(Manifest.permission.BLUETOOTH_CONNECT) == PackageManager.PERMISSION_GRANTED);
    }
    private final ScanCallback scanner = new ScanCallback() {
        @Override public void onScanResult(int type, ScanResult result) {
            if (result.getScanRecord() == null) return;
            byte[] ad = result.getScanRecord().getManufacturerSpecificData(0x0553);
            if (ad == null || ad.length < 7) return;
            int pid = (ad[5] & 255) | ((ad[6] & 255) << 8);
            if (pid != 0x2066 && pid != 0x2067 && pid != 0x2069 && pid != 0x2073) return;
            String mac = result.getDevice().getAddress();
            handler.post(() -> {
                if (!discovered.add(mac)) return;
                Button item = new Button(MainActivity.this);
                item.setText(String.format(Locale.ROOT, "%04x  %s", pid, mac));
                item.setOnClickListener(v -> connect(result.getDevice(), pid)); devices.addView(item);
            });
        }
        @Override public void onScanFailed(int code) { say("Scan failed: " + code); }
    };
    private void stopScan() {
        if (adapter != null && permitted() && adapter.getBluetoothLeScanner() != null)
            adapter.getBluetoothLeScanner().stopScan(scanner);
    }
    private void scan() {
        if (!permitted() || adapter == null || !adapter.isEnabled()) { say("Enable Bluetooth and grant Nearby Devices permissions"); return; }
        disconnect(); devices.removeAllViews(); discovered.clear();
        adapter.getBluetoothLeScanner().startScan(null, new ScanSettings.Builder().setScanMode(ScanSettings.SCAN_MODE_LOW_LATENCY).build(), scanner);
        handler.postDelayed(this::stopScan, 15000);
        say("Scanning for 15 seconds; hold SYNC");
    }
    private void connect(BluetoothDevice device, int pid) {
        disconnect(); closing = false; product = pid; address = device.getAddress();
        say("Connecting " + address);
        gatt = device.connectGatt(this, false, callback, BluetoothDevice.TRANSPORT_LE);
    }
    private void queue(Runnable operation) {
        if (operations.size() > 128) { fail("Output backpressure; stopping"); return; }
        operations.add(operation); runNext();
    }
    private void runNext() {
        if (busy || operations.isEmpty() || closing) return;
        busy = true; handler.postDelayed(timeout, 8000); operations.remove().run();
    }
    private void completed(int status) {
        handler.removeCallbacks(timeout);
        if (status != BluetoothGatt.GATT_SUCCESS) { fail("GATT error " + status); return; }
        busy = false; runNext();
    }
    private final BluetoothGattCallback callback = new BluetoothGattCallback() {
        @Override public void onConnectionStateChange(BluetoothGatt g, int status, int state) {
            handler.post(() -> {
                if (g != gatt) return;
                if (status != 0 || state == BluetoothProfile.STATE_DISCONNECTED) { fail("BLE disconnected: " + status); return; }
                if (state == BluetoothProfile.STATE_CONNECTED) {
                    if (!g.requestMtu(247)) fail("MTU request rejected");
                    else handler.postDelayed(timeout, 8000);
                }
            });
        }
        @Override public void onMtuChanged(BluetoothGatt g, int mtu, int status) {
            handler.post(() -> {
                if (g != gatt) return;
                handler.removeCallbacks(timeout);
                if (status != 0 || mtu < 80 || !g.discoverServices()) { fail("Need MTU >= 80 and GATT services"); return; }
                handler.postDelayed(timeout, 8000);
            });
        }
        @Override public void onServicesDiscovered(BluetoothGatt g, int status) {
            handler.post(() -> { if (g == gatt) services(status); });
        }
        @Override public void onDescriptorWrite(BluetoothGatt g, BluetoothGattDescriptor d, int status) {
            handler.post(() -> { if (g == gatt) completed(status); });
        }
        @Override public void onCharacteristicWrite(BluetoothGatt g, BluetoothGattCharacteristic c, int status) {
            handler.post(() -> { if (g == gatt) completed(status); });
        }
        @Override public void onCharacteristicChanged(BluetoothGatt g, BluetoothGattCharacteristic c) {
            byte[] data = c.getValue() == null ? null : c.getValue().clone();
            UUID uuid = c.getUuid();
            handler.post(() -> {
                if (g != gatt || relayIn == null || data == null) return;
                if (uuid.equals(INPUT)) forward(0x0a, data);
                else if (uuid.equals(ACK)) forward(0x1a, data);
            });
        }
    };
    private BluetoothGattCharacteristic find(UUID uuid) {
        for (BluetoothGattService service : gatt.getServices()) {
            BluetoothGattCharacteristic c = service.getCharacteristic(uuid);
            if (c != null) return c;
        }
        return null;
    }
    private void subscribe(BluetoothGattCharacteristic c) {
        queue(() -> {
            BluetoothGattDescriptor ccc = c.getDescriptor(CCC);
            if (ccc == null || !gatt.setCharacteristicNotification(c, true)) { fail("Notification setup failed"); return; }
            ccc.setValue(BluetoothGattDescriptor.ENABLE_NOTIFICATION_VALUE);
            if (!gatt.writeDescriptor(ccc)) fail("CCCD write rejected");
        });
    }
    private void services(int status) {
        handler.removeCallbacks(timeout);
        if (status != 0 || gatt.getService(SERVICE) == null) { fail("Switch 2 GATT service missing"); return; }
        command = find(COMMAND);
        String hapticUuid = product == 0x2067 ? "289326cb-a471-485d-a8f4-240c14f18241" :
            product == 0x2066 ? "fa19b0fb-cd1f-46a7-84a1-bbb09e00c149" :
            product == 0x2073 ? "3f8fb670-ab25-45bf-b540-38c72834d064" : "cc483f51-9258-427d-a939-630c31f72b05";
        haptic = find(UUID.fromString(hapticUuid));
        BluetoothGattCharacteristic input = find(INPUT), ack = find(ACK);
        if (command == null || haptic == null || input == null || ack == null) { fail("Required GATT UUID missing; no guessed handles"); return; }
        subscribe(input); subscribe(ack);
        queue(() -> { busy = false; handler.removeCallbacks(timeout); notificationsReady = true; startRelay(); });
    }
    private void kernelStatus() {
        new Thread(() -> {
            try {
                java.lang.Process p = new ProcessBuilder("su", "-c", "cat /sys/bus/hid/devices/*/switch2_status").start();
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(p.getInputStream()))) {
                    String line; while ((line = reader.readLine()) != null) say(line);
                }
                if (p.waitFor() != 0) say("No status: kernel driver missing, permission denied or not connected");
            } catch (Exception e) { say("Status unavailable: " + e); }
        }, "ns2-status").start();
    }
    private static String hex(byte[] data) {
        StringBuilder b = new StringBuilder();
        for (byte v : data) b.append(String.format(Locale.ROOT, "%02x", v & 255));
        return b.toString();
    }
    private void forward(int handle, byte[] data) {
        try { relayIn.write("I " + Integer.toHexString(handle) + " " + hex(data) + "\n"); relayIn.flush(); }
        catch (IOException e) { fail("UHID relay write failed: " + e); }
    }
    private void startRelay() {
        if (!notificationsReady || closing) return;
        final int session = generation;
        new Thread(() -> {
            try {
                String executable = getApplicationInfo().nativeLibraryDir + "/libns2relay.so";
                String cmd = "exec '" + executable + "' " + Integer.toHexString(product) + " " + address;
                java.lang.Process process = new ProcessBuilder("su", "-c", cmd).start();
                handler.post(() -> {
                    if (session != generation || closing) { process.destroy(); return; }
                    relay = process; relayIn = new BufferedWriter(new OutputStreamWriter(process.getOutputStream()));
                    handler.postDelayed(timeout, 8000);
                });
                new Thread(() -> {
                    try (BufferedReader err = new BufferedReader(new InputStreamReader(process.getErrorStream()))) {
                        String s; while ((s = err.readLine()) != null) say("relay: " + s);
                    } catch (IOException ignored) { }
                }).start();
                try (BufferedReader output = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
                    String line;
                    while ((line = output.readLine()) != null) {
                        final String event = line;
                        handler.post(() -> { if (session == generation && !closing) output(event); });
                    }
                }
                int result = process.waitFor();
                handler.post(() -> { if (session == generation && !closing) fail("relay ended: " + result); });
            } catch (Exception e) { handler.post(() -> { if (session == generation) fail("Root relay unavailable: " + e); }); }
        }, "ns2-relay").start();
    }
    private void output(String line) {
        if (line.equals("READY")) {
            handler.removeCallbacks(timeout);
            say("UHID transport open; kernel initializing. No hardware validation yet.");
            final int session = generation;
            // UHID_OPEN can precede completion of the asynchronous HID probe.
            for (int delay : new int[]{250, 1000}) handler.postDelayed(() -> {
                if (session == generation && relayIn != null && !closing) forward(0, new byte[]{0});
            }, delay);
            return;
        }
        if (!line.startsWith("O ")) { say(line); return; }
        String[] parts = line.split(" ");
        try {
            if (parts.length != 3 || parts[2].length() % 2 != 0) throw new IllegalArgumentException();
            int handle = Integer.parseInt(parts[1], 16);
            BluetoothGattCharacteristic target = handle == 0x14 ? command : handle == 0x12 ? haptic : null;
            if (target == null || parts[2].length() > 128) throw new IllegalArgumentException();
            byte[] value = new byte[parts[2].length() / 2];
            for (int i = 0; i < value.length; i++) value[i] = (byte)Integer.parseInt(parts[2].substring(i * 2, i * 2 + 2), 16);
            queue(() -> {
                target.setWriteType(BluetoothGattCharacteristic.WRITE_TYPE_NO_RESPONSE);
                target.setValue(value);
                if (!gatt.writeCharacteristic(target)) fail("GATT output rejected");
            });
        } catch (IllegalArgumentException e) { fail("Invalid kernel relay frame"); }
    }
    private void disconnect() {
        closing = true; generation++;
        handler.removeCallbacks(timeout); handler.removeCallbacksAndMessages(null);
        stopScan(); operations.clear(); busy = false; notificationsReady = false;
        if (relayIn != null) { try { relayIn.close(); } catch (IOException ignored) { } relayIn = null; }
        if (relay != null) { relay.destroy(); relay = null; }
        if (gatt != null) { gatt.disconnect(); gatt.close(); gatt = null; }
    }
    @Override protected void onDestroy() { disconnect(); super.onDestroy(); }
}
