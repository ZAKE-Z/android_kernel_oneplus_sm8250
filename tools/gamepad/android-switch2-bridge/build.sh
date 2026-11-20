#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-2.0
set -euo pipefail
HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
SDK="${ANDROID_HOME:-$HOME/Android/Sdk}"
NDK="${ANDROID_NDK_HOME:-$SDK/ndk/27.0.12077973}"
JAVA="${JAVA_HOME:-$(dirname "$(dirname "$(readlink -f "$(command -v java)")")")}"
BT="${BUILD_TOOLS:-$SDK/build-tools/35.0.0}"
JAR="${ANDROID_JAR:-$SDK/platforms/android-36/android.jar}"
OUT="${OUT_DIR:-$HOME/kbuild/android-switch2-bridge}"
mkdir -p "$OUT/classes" "$OUT/dex" "$OUT/package/lib/arm64-v8a"
export JAVA_HOME="$JAVA" PATH="$JAVA/bin:$PATH"
"$NDK/toolchains/llvm/prebuilt/linux-x86_64/bin/aarch64-linux-android26-clang" \
	-std=gnu11 -Wall -Wextra -Werror -O2 -fPIE -pie "$HERE/relay.c" \
	-o "$OUT/package/lib/arm64-v8a/libns2relay.so"
"$JAVA/bin/javac" -encoding UTF-8 -source 8 -target 8 -Xlint:-options -classpath "$JAR" \
	-d "$OUT/classes" "$HERE/src/org/oppo/gamepad/ns2bridge/MainActivity.java"
mapfile -t CLASSES < <(find "$OUT/classes" -name '*.class')
"$BT/d8" --min-api 26 --lib "$JAR" --output "$OUT/dex" "${CLASSES[@]}"
"$BT/aapt2" link -I "$JAR" --manifest "$HERE/AndroidManifest.xml" \
	-o "$OUT/unsigned.apk"
cp "$OUT/dex/classes.dex" "$OUT/package/classes.dex"
python3 - "$OUT" <<'PY'
import pathlib,sys,zipfile
out=pathlib.Path(sys.argv[1])
with zipfile.ZipFile(out/'unsigned.apk', 'a', compression=zipfile.ZIP_DEFLATED) as z:
    for p in (out/'package').rglob('*'):
        if p.is_file(): z.write(p,p.relative_to(out/'package'))
PY
"$BT/zipalign" -f 4 "$OUT/unsigned.apk" "$OUT/aligned.apk"
if [[ ! -f "$OUT/lab.keystore" ]]; then
	"$JAVA/bin/keytool" -genkeypair -keystore "$OUT/lab.keystore" -storepass android \
		-keypass android -alias lab -keyalg RSA -keysize 2048 -validity 3650 \
		-dname "CN=Local experimental gamepad build" -noprompt
fi
"$BT/apksigner" sign --ks "$OUT/lab.keystore" --ks-pass pass:android \
	--key-pass pass:android --out "$OUT/Switch2-BLE-Lab-UNTESTED.apk" "$OUT/aligned.apk"
"$BT/apksigner" verify "$OUT/Switch2-BLE-Lab-UNTESTED.apk"
echo "Experimental APK (not installed): $OUT/Switch2-BLE-Lab-UNTESTED.apk"
