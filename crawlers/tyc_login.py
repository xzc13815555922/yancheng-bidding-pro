#!/usr/bin/env python3
"""
tyc_login.py — 天眼查扫码登录工具

功能：
  1. 用 Playwright 打开天眼查网页首页
  2. 等待用户手动扫码登录
  3. 检测登录成功（检查页面 URL/元素变化）
  4. 保存 Cookie 到 data/cookies.json
  5. 可选验证：打开搜索页测试 Cookie 有效性

用法：
    cd ~/.openclaw/workspace/yancheng-bidding-pro
    python3 crawlers/tyc_login.py              # 扫码登录并保存 Cookie
    python3 crawlers/tyc_login.py --verify-only # 仅验证已有 Cookie，不重新登录

⚠️ 注意：
    - 需要先安装 Playwright：pip install playwright && playwright install chromium
    - Cookie 有效期约 7-30 天（天眼查会员）
    - 建议每周一自动触发一次登录检查

返回码：
    0 = 登录成功 / Cookie 有效
    1 = 登录失败 / 取消
    2 = Cookie 过期 / 无效
"""

import json
import os
import sys
import time
from datetime import datetime

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COOKIE_PATH = os.path.join(SKILL_DIR, "data", "cookies.json")


def detect_login_success(page) -> bool:
    """
    检测是否已登录天眼查。
    通过检查页面 URL 和关键元素判断。

    判断逻辑：
        - URL 未跳转到 login 相关路径
        - 页面存在已登录的用户元素（如头像、用户名区域）
    """
    current_url = page.url.lower()
    if "login" in current_url or "passport" in current_url:
        return False

    # 检查已登录特征元素
    login_indicators = [
        ".user-info",
        ".user-head",
        ".avatar-box",
        ".login-user",
        ".userAvatar",
        "a[href*='usercenter']",
        "a[href*='/uc/']",
        "[class*='userAvatar']",
        "[class*='user-head']",
        "[class*='login-user']",
    ]
    for sel in login_indicators:
        try:
            if page.locator(sel).first.count() > 0:
                return True
        except Exception:
            continue

    # 兜底：没有"登录/注册"链接 = 已登录
    try:
        btn = page.locator("a:has-text('登录/注册'), button:has-text('登录')").first
        if btn.count() == 0:
            return True
    except Exception:
        pass

    return False


def tyc_login(headless: bool = False, keep_alive: bool = False, keep_alive_timeout: int = 0) -> bool:
    """
    用 Playwright 打开天眼查，等待用户扫码登录。

    参数：
        headless: 是否无头模式（默认 False = 有窗口）
        keep_alive: 登录后保持浏览器打开（老板要操作天眼查时用）
                    True  → 登录成功后不 browser.close()，等 keep_alive_timeout 秒
                    False → 登录成功后立即关闭（原行为）
        keep_alive_timeout: 保持 N 秒后自动关（默认 0 = 永久，需手动 Ctrl+C 或关窗口）
                            仅在 keep_alive=True 时生效

    返回：True=登录成功，False=登录失败/取消
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 未安装 Playwright，请运行：")
        print("   pip install playwright && playwright install chromium")
        sys.exit(1)

    def _close_browser():
        if not keep_alive:
            browser.close()

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=headless,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()

        print("🚀 打开天眼查首页...")
        page.goto("https://www.tianyancha.com", wait_until="networkidle")
        time.sleep(2)

        # 先试试已有 Cookie 是否还有效（用 jingzhuang 页验证，比首页更严格）
        if os.path.exists(COOKIE_PATH):
            with open(COOKIE_PATH, "r") as f:
                old_cookies = json.load(f)
            context.add_cookies(old_cookies)
            # 访问需会员权限的页面（盐城移动 jingzhuang）
            page.goto("https://www.tianyancha.com/company/2954073051/jingzhuang", wait_until="commit")
            time.sleep(3)
            url_after = page.url.lower()
            # 如果跳转到登录页 or 页面包含"请登录"提示 → Cookie 失效
            if "login" in url_after or "passport" in url_after:
                print("⚠️  已有 Cookie 已过期，需要重新扫码")
            else:
                body = page.locator("body").inner_text()
                if "请登录" in body or "登录后查看" in body:
                    print("⚠️  已有 Cookie 会员权限失效，需要重新扫码")
                else:
                    print("✅ 已有 Cookie 仍有效，无需重新登录")
                    if not keep_alive:
                        browser.close()
                        return True
                    # keep_alive=True 也支持已登录场景：保存 cookie + 保持窗口
                    with open(COOKIE_PATH, "w") as f:
                        json.dump(old_cookies, f, ensure_ascii=False, indent=2)
                    print(f"✅ Cookie 已保存（{len(old_cookies)} 条）")
                    _wait_for_user(browser, keep_alive_timeout, "✅ 浏览器已打开（用现有 Cookie），按 Ctrl+C 或关闭窗口结束...")
                    return True

        # 等待用户扫码：固定等 90 秒，不做轮询检测
        print("\n🔑 请在浏览器中扫码登录天眼查...")
        print("   如果首页没有弹出二维码，手动点击'登录'按钮")
        print("   扫码完成后等待 90 秒自动继续（无需手动操作）...")
        time.sleep(90)

        # 保存当前 Cookie（不管是否成功，先存下来）
        cookies = context.cookies()
        os.makedirs(os.path.dirname(COOKIE_PATH), exist_ok=True)
        with open(COOKIE_PATH, "w") as f:
            json.dump(cookies, f, ensure_ascii=False, indent=2)

        # 用 jingzhuang 页验证是否真正登录（会员权限）
        print("🔍 验证登录态（访问会员页面）...")
        page.goto("https://www.tianyancha.com/company/2954073051/jingzhuang", wait_until="commit")
        time.sleep(5)
        url_after = page.url.lower()
        body = page.locator("body").inner_text()

        if "login" in url_after or "passport" in url_after:
            print("❌ Cookie 无效（跳转到登录页），请重试")
            _close_browser()
            return False

        # 检查 jingzhuang 页是否有表格数据（真正会员才能看到）
        tr_count = page.locator("tr").count()
        if tr_count >= 3:
            print(f"✅ 登录验证通过（jingzhuang 表格 {tr_count} 行）")
            print(f"✅ Cookie 已保存到 {COOKIE_PATH} ({len(cookies)} 条)")
            if keep_alive:
                _wait_for_user(browser, keep_alive_timeout, f"✅ 浏览器已打开（{len(cookies)} 条 Cookie），按 Ctrl+C 或关闭窗口结束...")
                return True
            browser.close()
            return True
        else:
            print(f"❌ 登录验证失败（表格行数 {tr_count}，可能未登录或非会员）")
            print(f"   当前 URL: {page.url}")
            _close_browser()
            return False


def _wait_for_user(browser, timeout: int, message: str):
    """
    keep_alive 模式下保持浏览器打开，等待用户手动结束。
    timeout > 0：到点自动关；timeout == 0：永久等待直到 Ctrl+C 或关窗口。
    """
    print()
    print("=" * 60)
    print(message)
    if timeout > 0:
        print(f"   {timeout} 秒后自动关闭")
    else:
        print("   永久保持（按 Ctrl+C 干净退出，Cookie 不会丢）")
    print("=" * 60)
    try:
        if timeout > 0:
            time.sleep(timeout)
            print(f"\n⏰ {timeout} 秒到，自动关闭浏览器")
        else:
            # 永久：等用户 Ctrl+C（KeyboardInterrupt）或关窗口（playwright wait）
            while True:
                time.sleep(1)
                # 检查 browser 是否已被用户关
                if not browser.is_connected():
                    print("\n🪟 浏览器窗口被用户关闭")
                    return
    except KeyboardInterrupt:
        print("\n🛑 用户 Ctrl+C，准备关闭浏览器...")
    finally:
        try:
            browser.close()
        except Exception:
            pass


def verify_cookie() -> bool:
    """
    验证 data/cookies.json 是否有效。
    用 Cookie 搜索一个关键词，判断是否返回正常结果（非登录页）。

    返回：True=有效，False=过期
    """
    if not os.path.exists(COOKIE_PATH):
        print("❌ Cookie 文件不存在")
        return False

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("❌ 未安装 Playwright")
        return False

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
        )

        # 加载 Cookie
        with open(COOKIE_PATH, "r") as f:
            cookies = json.load(f)
        context.add_cookies(cookies)

        page = context.new_page()

        # 搜索测试
        page.goto(
            "https://www.tianyancha.com/search?key=中标",
            wait_until="networkidle",
        )
        time.sleep(3)

        current_url = page.url.lower()

        # 判断是否被重定向到登录页
        if "login" in current_url or "passport" in current_url:
            print(f"⚠️  Cookie 已过期，被重定向到登录页")
            print(f"   请运行 python3 scripts/tyc_login.py 重新扫码")
            browser.close()
            return False

        # 检查是否有搜索结果
        result_count = page.locator(".search_result_single").count()
        if result_count > 0:
            print(f"✅ Cookie 有效，搜索结果页面正常（{result_count} 条结果）")
            browser.close()
            return True

        # 兜底检查：页面不为空且不是登录页
        body_has_content = len(page.locator("body").inner_text().strip()) > 500
        if body_has_content:
            print(f"✅ Cookie 可能有效（页面有内容，且未被重定向到登录页）")
            browser.close()
            return True

        print("⚠️  页面无内容，Cookie 可能无效")
        browser.close()
        return False


def main():
    import argparse

    parser = argparse.ArgumentParser(description="天眼查扫码登录工具")
    parser.add_argument(
        "--verify-only",
        action="store_true",
        help="仅验证已有 Cookie，不重新登录",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="无头模式（用于调试）",
    )
    parser.add_argument(
        "--keep-alive", "-k",
        action="store_true",
        help="登录后保持浏览器打开（老板手动操作天眼查时用）",
    )
    parser.add_argument(
        "--keep-alive-timeout",
        type=int,
        default=0,
        metavar="SEC",
        help="保持 N 秒后自动关闭（默认 0=永久，需要手动 Ctrl+C 或关窗口）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  天眼查登录工具")
    print("=" * 60)
    print()

    if args.verify_only:
        print("🔍 验证 Cookie 有效性...")
        valid = verify_cookie()
        print()
        if valid:
            print("✅ Cookie 有效。")
            sys.exit(0)
        else:
            print("❌ Cookie 无效，请运行 python3 scripts/tyc_login.py 重新登录。")
            sys.exit(2)
    else:
        success = tyc_login(
            headless=args.headless,
            keep_alive=args.keep_alive,
            keep_alive_timeout=args.keep_alive_timeout,
        )
        print()
        if success:
            if args.keep_alive:
                # keep_alive 路径已在 _wait_for_user 等待，这里不会到这里
                print(f"✅ 登录成功，浏览器已关闭。")
            else:
                print(f"✅ 登录成功，Cookie 已保存。")
            sys.exit(0)
        else:
            print("❌ 登录失败，请重试。")
            sys.exit(1)


if __name__ == "__main__":
    main()
