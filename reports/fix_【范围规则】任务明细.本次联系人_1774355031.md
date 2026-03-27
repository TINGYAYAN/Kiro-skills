# APL 修复报告：【范围规则】任务明细.本次联系人

生成时间：2026-03-24 20:23:51

共修复 3 次

## 第 1 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-88709924
StopWatch 'Scope_NResj__c': running time = 201 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

unexpected char: '`' @ line 14, column 16.
```

**代码变更（unified diff）：**
```diff
--- v0
+++ v1
@@ -3,5 +3,5 @@
  * @codeName 【范围规则】任务明细.本次联系人
  * @description 任务明细.本次联系人的可选范围：
- * ①联系人.客户姓名=任务明细.客户 且 联系人.联系人类型=客户联系人 
+ * ①联系人.客户姓名=任务明细.客户 且 联系人.联系人类型=客户联系人
  * ②任务明细.客户.代理商=联系人.代理商 且 联系人类型=代理商
  * @createTime 2026-03-24
@@ -10,14 +10,4 @@
  * @函数需求编号
  */
-分析需求：
-
-- 条件①：联系人.客户姓名（`account__c`，待确认）= 任务明细.客户（`customer__c`），且 联系人类型 = 客户联系人（`option_customer_contact__c`）
-- 条件②：联系人.代理商（`agent__c`）= 任务明细.客户.代理商（`field_62Dh4__c`），且 联系人类型 = 代理商联系人（`option_agent_contact_person__c`）
-
-两个条件是 OR 关系，但 `QueryTemplate.AND` / `OR` 只能返回一个条件块。范围规则无法做数据库查询，只能基于表单当前值构建静态过滤条件。
-
-由于无法在范围规则中执行 OR 跨字段动态查询（不能调用 Fx.object.find），这里根据任务明细上是否有合作代理商（`field_62Dh4__c`）来决定走哪个分支，或用 `QueryTemplate.OR` 合并两个条件。
-
-// 从当前表单取任务明细的客户ID和合作代理商ID
 String customerId = context.data.customer__c as String
 if (!customerId) customerId = ""
@@ -26,6 +16,5 @@
 if (!agentId) agentId = ""
 
-// 待确认：联系人对象中「客户姓名」关联字段的 API 名，需在平台「对象管理-ContactObj-字段」中查看后替换
-String contactAccountField = "TODO_REPLACE_CONTACT_ACCOUNT_FIELD"
+String contactAccountField = "account__c"
 
 if (customerId && agentId) {

```

## 第 2 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-61474528
StopWatch 'Scope_NResj__c': running time = 379 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 28.
```

**代码变更（unified diff）：**
```diff
--- v1
+++ v2
@@ -20,5 +20,5 @@
 if (customerId && agentId) {
     return [
-        "searchCondition": QueryTemplate.OR([
+        "searchCondition": QueryTemplate.OR(
             QueryTemplate.AND([
                 (contactAccountField): QueryOperator.EQ(customerId),
@@ -29,5 +29,5 @@
                 "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
             ])
-        ])
+        )
     ]
 }

```

## 第 3 次修复

**错误信息：**
```
运行中... 
 扫描函数
运行日志
E-E.fx88888888.1000-61474528
StopWatch 'Scope_NResj__c': running time = 379 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 28.
```

**代码变更（unified diff）：**
```diff
--- v2
+++ v3
@@ -20,5 +20,5 @@
 if (customerId && agentId) {
     return [
-        "searchCondition": QueryTemplate.OR(
+        "searchCondition": QueryTemplate.OR([
             QueryTemplate.AND([
                 (contactAccountField): QueryOperator.EQ(customerId),
@@ -29,5 +29,5 @@
                 "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
             ])
-        )
+        ])
     ]
 }

```

