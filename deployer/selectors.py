"""
纷享销客函数管理页面 CSS/XPath 选择器。

若纷享 UI 升级导致选择器失效，在此统一修改。
可通过 Playwright Inspector（PWDEBUG=1）录制获取新选择器。
"""

# ----- 登录页 -----
# 切换到「账号登录」tab（纷享新 UI 默认 QR 扫码，需点击 Account/账号 才显示输入框）
LOGIN_ACCOUNT_TAB = ':text("账号登录")'
LOGIN_ACCOUNT_TAB_ALT = [
    ':text("Account")', ':text-is("Account")',  # 新 UI 英文 tab
    ':text("账号密码登录")', ':text("密码登录")', 'button:has-text("账号")', 'button:has-text("Account")',
    '[role="tab"]:has-text("账号")', '[role="tab"]:has-text("Account")',
]

# 账号输入框（按优先级尝试，纷享 UI 升级后 placeholder 可能变化）
LOGIN_USERNAME = 'input[placeholder*="手机"], input[placeholder*="账号"], input[placeholder*="邮箱"], input[type="tel"]'
LOGIN_USERNAME_ALT = [
    'input[placeholder*="手机"]', 'input[placeholder*="账号"]', 'input[placeholder*="邮箱"]',
    'input[placeholder*="用户名"]', 'input[type="tel"]', 'input[type="text"]',
    'input[autocomplete="username"]', 'input[name*="user"]', 'input[name*="account"]',
]

# 密码输入框（新 UI 可能用英文 placeholder）
LOGIN_PASSWORD = 'input[placeholder*="密码"], input[placeholder*="password"], input[type="password"]'
LOGIN_PASSWORD_ALT = [
    'input[type="password"]', 'input[placeholder*="密码"]', 'input[placeholder*="Password"]',
    'input[placeholder*="password"]', 'input[autocomplete="current-password"]',
]

# 服务协议勾选框
LOGIN_AGREEMENT = ':text("我已阅读并同意"), input[type="checkbox"] + *:has-text("服务协议"), .agreement-checkbox'
# 登录按钮（纷享用 div/span 模拟按钮，不是标准 button）
LOGIN_SUBMIT = ':text-is("登录"), button:has-text("登录"), [class*="login-btn"], [class*="loginBtn"]'

# ----- 函数列表页 -----
# 搜索框（必须精确匹配函数表格区域的搜索框，避免误触左侧导航栏的 "搜索" 输入框）
FUNC_SEARCH_INPUT = 'input[placeholder*="搜索代码名称"]'
FUNC_SEARCH_INPUT_ALT = [
    'input[placeholder*="搜索代码名称"]', 'input[placeholder*="Search"]',
    'input[placeholder*="搜索"]', 'input[placeholder*="函数"]',
]
# 函数列表行（含函数名文字的 tr）
FUNC_LIST_ITEM = 'table tbody tr'
# 新建按钮（右上角，可能是 div/span 而非 button）
FUNC_NEW_BTN = ':text("新建APL函数")'
FUNC_NEW_BTN_ALT = [
    ':text("新建APL函数")', ':text("新建自定义APL函数")', ':text("添加自定义函数")',
    ':text("新建函数")', ':text("添加函数")', ':text("新建")',
    'button:has-text("新建")', '[class*="new"]:has-text("新建")',
    ':text("New")', ':text("Create")', ':text("Add")',
]

# ----- 新建APL函数弹窗（第一步：填写元信息）-----
# 弹窗里的「下一步」按钮
FUNC_NEXT_BTN = ':text("下一步")'
# 弹窗取消按钮
FUNC_CANCEL_BTN = ':text("取消")'

# ----- 代码编辑页（第二步：填写代码）-----
# 代码编辑器（CodeMirror）
CODE_EDITOR_CONTAINER = '.CodeMirror'
CODE_EDITOR_FOCUS = '.CodeMirror-code'
# 保存/确认按钮（精确匹配，避免误匹配含"保存"的段落文字）
FUNC_SAVE_BTN = ':text-is("保存"), :text-is("确认"), :text-is("提交")'
# 确认弹窗
CONFIRM_BTN = ':text("确定")'

# ----- 函数列表页操作 -----
# 列表里每行的「编辑」链接（精确匹配，避免误选含"编辑"的父容器）
FUNC_EDIT_LINK = ':text-is("编辑")'

# ----- 消息提示 -----
SUCCESS_TOAST = '.el-message--success, [class*="success-message"]'
ERROR_TOAST = '.el-message--error, [class*="error-message"]'
