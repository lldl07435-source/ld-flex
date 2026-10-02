"""Build the same controller for desktop simulation and STM32."""
from pathlib import Path
import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]

def compiler(arm=False):
    name = 'arm-none-eabi-gcc' if arm else 'gcc'
    found = os.environ.get('ARM_GCC' if arm else 'CC') or shutil.which(name)
    if found:
        return found
    candidates = glob.glob('D:/STM32Workspace/STM32CubeIDE*/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32.*/tools/bin/arm-none-eabi-gcc.exe') if arm else ['C:/mingw64/bin/gcc.exe']
    for path in candidates:
        if Path(path).is_file():
            return path
    raise RuntimeError(f'{name} not found. Set {"ARM_GCC" if arm else "CC"} to the compiler path; see docs/实操手册.md')

def build(arm=False):
    folder = ROOT / 'build'
    folder.mkdir(exist_ok=True)
    cc = compiler(arm)
    common = [cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2', '-Icore', 'core/cell.c', 'core/wire.c']
    if arm:
        output = folder / 'ld-flex.elf'
        cmd = common + ['-mcpu=cortex-m3', '-mthumb', '-ffunction-sections', '-fdata-sections', '-nostartfiles', '--specs=nano.specs', '--specs=nosys.specs', 'firmware/startup.S', 'firmware/main.c', '-Tfirmware/linker.ld', '-Wl,--gc-sections', '-Wl,-Map=build/ld-flex.map', '-o', str(output)]
    else:
        output = folder / ('ldcell.dll' if os.name == 'nt' else 'libldcell.so')
        cmd = common + ['-shared', '-DLD_SHARED', '-o', str(output)]
        if os.name != 'nt': cmd += ['-fPIC']
    print(subprocess.check_output([cc, '--version'], text=True).splitlines()[0])
    subprocess.run(cmd, cwd=ROOT, check=True)
    if not arm:
        source={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted((ROOT/'core').glob('*')) if p.suffix in ('.c','.h')}
        (folder/'source_stamp.json').write_text(json.dumps({'source':source,'library_sha256':hashlib.sha256(output.read_bytes()).hexdigest()},indent=2),encoding='utf-8')
    if arm:
        objcopy = str(Path(cc).with_name('arm-none-eabi-objcopy' + ('.exe' if os.name == 'nt' else '')))
        subprocess.run([objcopy, '-O', 'binary', str(output), str(folder / 'ld-flex.bin')], check=True)
    print(output)
    return output

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', action='store_true')
    build(parser.parse_args().arm)
