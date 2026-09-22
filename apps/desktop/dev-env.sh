#!/usr/bin/env bash
# MiniYuxi 桌面端 · Windows MSVC 开发环境（Git Bash 用）
#
# 用法：
#   source apps/desktop/dev-env.sh      # 之后 cargo / tauri 直接可用
#   source apps/desktop/dev-env.sh && cargo check
#
# 为什么需要它：
#   1) Git Bash 自带的 GNU `link`（建硬链接用）会抢在 MSVC link.exe 前面，
#      rustc 一调用链接器就报 "link: extra operand ..."；
#   2) 没有 LIB / INCLUDE，链接器找不到 kernel32.lib（LNK1181）。
#   本脚本把 MSVC bin 提到 PATH 最前，并自动探测 MSVC / Windows SDK 版本补齐 LIB / INCLUDE，
#   等价于官方 vcvars64.bat，但不依赖 cmd.exe。

# 两套写法都要：bash 只认 POSIX(/c/...)，Windows 程序只认盘符(C:/...)，
# 传给 Windows 子进程时 MSYS 会把 POSIX 形式自动转成盘符形式，两者都放最稳妥。
MSVC_ROOT_POSIX="/c/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC"
MSVC_ROOT_WIN="C:/Program Files (x86)/Microsoft Visual Studio/2022/BuildTools/VC/Tools/MSVC"
SDK_ROOT="C:/Program Files (x86)/Windows Kits/10"
CARGO_BIN="$HOME/.cargo/bin"

if [ ! -d "$MSVC_ROOT_POSIX" ]; then
  echo "[dev-env] ✗ 未找到 MSVC：$MSVC_ROOT_POSIX（先装 VS2022 BuildTools + VCTools）" >&2
  return 1 2>/dev/null || exit 1
fi

# 取版本最高的 MSVC 工具集与 SDK
MSVC_VER=$(ls -1 "$MSVC_ROOT_POSIX" | sort -V | tail -1)
SDK_VER=$(ls -1 "$SDK_ROOT/Lib" 2>/dev/null | grep -E '^10\.' | sort -V | tail -1)

export LIB="$MSVC_ROOT_WIN/$MSVC_VER/lib/x64;$SDK_ROOT/Lib/$SDK_VER/ucrt/x64;$SDK_ROOT/Lib/$SDK_VER/um/x64"
export INCLUDE="$MSVC_ROOT_WIN/$MSVC_VER/include;$SDK_ROOT/Include/$SDK_VER/ucrt;$SDK_ROOT/Include/$SDK_VER/um;$SDK_ROOT/Include/$SDK_VER/shared;$SDK_ROOT/Include/$SDK_VER/winrt"
# MSVC bin 必须在最前，压掉 Git Bash 的 GNU link
export PATH="$MSVC_ROOT_POSIX/$MSVC_VER/bin/Hostx64/x64:$MSVC_ROOT_WIN/$MSVC_VER/bin/Hostx64/x64:$CARGO_BIN:$PATH"

echo "[dev-env] MSVC $MSVC_VER · SDK $SDK_VER · rustc $(rustc --version | awk '{print $2}')"
echo "[dev-env] link → $(command -v link.exe)"
