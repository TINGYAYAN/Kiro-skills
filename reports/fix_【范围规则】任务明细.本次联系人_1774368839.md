# APL 修复报告：【范围规则】任务明细.本次联系人

生成时间：2026-03-25 00:13:59

共修复 2 次

## 第 1 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-90445252
StopWatch 'Scope_MJGCG__c': running time = 206 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

unexpected char: '`' @ line 52, column 1.
```

**代码变更（unified diff）：**
```diff
--- v0
+++ v1
@@ -1,18 +1,6 @@
-/**
- * @author 纷享实施人员
- * @codeName 【范围规则】任务明细.本次联系人
- * @description 任务明细.本次联系人的可选范围：
- * ①联系人.客户姓名=任务明细.客户 且 联系人.联系人类型=客户联系人 
- * ②任务明细.客户.代理商=联系人.代理商 且 联系人类型=代理商
- * @createTime 2026-03-25
- * @bindingObjectLabel 任务明细
- * @bindingObjectApiName task_detail__c
- * @函数需求编号
- */
 // 待确认：联系人对象中「客户姓名」关联字段的 API 名，需在平台对象管理-ContactObj-字段中查看后替换（当前推断为 account__c）
 String customerId = context.data.customer__c as String
 if (!customerId) customerId = ""
 
-// field_62Dh4__c 为任务明细.合作代理商（List 类型），取第一个元素作为代理商 ID
 List partnerList = context.data.field_62Dh4__c as List
 String agentId = ""
@@ -21,13 +9,4 @@
 }
 if (!agentId) agentId = ""
-
-if (customerId && agentId) {
-    return [
-        "searchCondition": QueryTemplate.AND([
-            "account__c": QueryOperator.EQ(customerId),
-            "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
-        ])
-    ]
-}
 
 if (customerId) {
@@ -49,14 +28,3 @@
 }
 
-return [:]
-```
-
----
-
-几点说明：
-
-1. **`account__c`（待确认）**：联系人对象中「客户姓名」关联字段的 API 名在提供的字段列表中未出现，参考历史示例推断为 `account__c`，需在平台「对象管理 - ContactObj - 字段」中核实后替换。
-
-2. **OR 条件拆分为多分支**：按规范，`QueryTemplate.OR` 需要租户额外开通，默认改写为 `if / else if` 多分支。当 `customerId` 和 `agentId` 同时存在时，优先返回条件①（客户联系人），条件②（代理商联系人）在仅有 `agentId` 时返回。如果业务上两个条件必须同时生效（即同一个弹窗里既显示客户联系人又显示代理商联系人），需确认租户已开通 OR 支持后，改用 `QueryTemplate.OR([...])` 写法。
-
-3. **`field_62Dh4__c` 为 List**：任务明细的合作代理商字段是多选关联，取第一个元素作为代理商 ID 传入条件。如业务上需匹配列表中任意一个代理商，需改用 `QueryOperator.IN(partnerList)`。+return [:]
```

## 第 2 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-58127997
StopWatch 'Scope_MJGCG__c': running time = 348 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
{}
```

**代码变更（unified diff）：**
```diff
--- v1
+++ v2
@@ -1,3 +1,2 @@
-// 待确认：联系人对象中「客户姓名」关联字段的 API 名，需在平台对象管理-ContactObj-字段中查看后替换（当前推断为 account__c）
 String customerId = context.data.customer__c as String
 if (!customerId) customerId = ""
@@ -12,8 +11,8 @@
 if (customerId) {
     return [
-        "searchCondition": QueryTemplate.AND([
+        "searchCondition": QueryTemplate.AND(
             "account__c": QueryOperator.EQ(customerId),
             "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
-        ])
+        )
     ]
 }
@@ -21,8 +20,8 @@
 if (agentId) {
     return [
-        "searchCondition": QueryTemplate.AND([
+        "searchCondition": QueryTemplate.AND(
             "agent__c": QueryOperator.EQ(agentId),
             "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
-        ])
+        )
     ]
 }

```

