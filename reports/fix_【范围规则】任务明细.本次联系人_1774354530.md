# APL 修复报告：【范围规则】任务明细.本次联系人

生成时间：2026-03-24 20:15:30

共修复 6 次

## 第 1 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-43284350
StopWatch 'Scope_B3Z73__c': running time = 197 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

unexpected char: '`' @ line 39, column 1.
```

**代码变更（unified diff）：**
```diff
--- v0
+++ v1
@@ -3,22 +3,16 @@
  * @codeName 【范围规则】任务明细.本次联系人
  * @description 任务明细.本次联系人的可选范围：
- * ①联系人.客户姓名=任务明细.客户 且 联系人.联系人类型=客户联系人 
+ * ①联系人.客户姓名=任务明细.客户 且 联系人.联系人类型=客户联系人
  * ②任务明细.客户.代理商=联系人.代理商 且 联系人类型=代理商
  * @createTime 2026-03-24
  * @bindingObjectLabel 任务明细
  * @bindingObjectApiName task_detail__c
- * @函数需求编号
  */
-// 从当前表单取客户字段值
 String customerId = context.data.customer__c as String
 if (!customerId) customerId = ""
 
-// 取任务明细.客户.代理商（客户对象上的代理商字段）
-// 待确认：customer__c 是关联字段，代理商需从客户记录取；此处取任务明细上的合作代理商字段作为代理商条件
-// 若任务明细上有直接存储代理商ID的字段，请替换 field_62Dh4__c
 String agentId = context.data.field_62Dh4__c as String
 if (!agentId) agentId = ""
 
-// 条件①：联系人.客户姓名=任务明细.客户 且 联系人类型=客户联系人
 if (customerId) {
     return [
@@ -36,8 +30,3 @@
 }
 
-return [:]
-```
-
-> **待确认事项**：
-> 1. 联系人中「客户姓名」对应的关联客户字段 API 名在字段列表中未列出，代码中用了 `account_id`，需在平台「对象管理-联系人-字段」中确认实际 API 名并替换。
-> 2. 「任务明细.客户.代理商」的取值路径：若任务明细表单上没有直接存储代理商 ID 的字段，范围规则无法跨对象查询，需确认是否有冗余字段（当前用 `field_62Dh4__c` 合作代理商字段代替）。+return [:]
```

## 第 2 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-6385138
StopWatch 'Scope_B3Z73__c': running time = 447 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 19, column 28.
```

**代码变更（unified diff）：**
```diff
--- v1
+++ v2
@@ -16,15 +16,10 @@
 
 if (customerId) {
+    List<Map<String, Object>> orList = [
+        QueryTemplate.AND(["account_id": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
+        QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
+    ] as List<Map<String, Object>>
     return [
-        "searchCondition": QueryTemplate.OR([
-            QueryTemplate.AND([
-                "account_id": QueryOperator.EQ(customerId),
-                "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
-            ]),
-            QueryTemplate.AND([
-                "agent__c": QueryOperator.EQ(agentId),
-                "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
-            ])
-        ])
+        "searchCondition": QueryTemplate.OR(orList as Map<String, Object>)
     ]
 }

```

## 第 3 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-13367481
StopWatch 'Scope_B3Z73__c': running time = 368 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

expecting '}', found 'return' @ line 22, column 5.
```

**代码变更（unified diff）：**
```diff
--- v2
+++ v3
@@ -1,12 +1,2 @@
-/**
- * @author 纷享实施人员
- * @codeName 【范围规则】任务明细.本次联系人
- * @description 任务明细.本次联系人的可选范围：
- * ①联系人.客户姓名=任务明细.客户 且 联系人.联系人类型=客户联系人
- * ②任务明细.客户.代理商=联系人.代理商 且 联系人类型=代理商
- * @createTime 2026-03-24
- * @bindingObjectLabel 任务明细
- * @bindingObjectApiName task_detail__c
- */
 String customerId = context.data.customer__c as String
 if (!customerId) customerId = ""
@@ -15,4 +5,6 @@
 if (!agentId) agentId = ""
 
+Map<String, Object> result = [:]
+
 if (customerId) {
     List<Map<String, Object>> orList = [
@@ -20,8 +12,6 @@
         QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
     ] as List<Map<String, Object>>
-    return [
-        "searchCondition": QueryTemplate.OR(orList as Map<String, Object>)
-    ]
+    result = ["searchCondition": QueryTemplate.OR(orList)]
 }
 
-return [:]+return result
```

## 第 4 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-62730679
StopWatch 'Scope_B3Z73__c': running time = 423 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

expecting '}', found 'result' @ line 14, column 5.
```

**代码变更（unified diff）：**
```diff
--- v3
+++ v4
@@ -8,8 +8,8 @@
 
 if (customerId) {
-    List<Map<String, Object>> orList = [
+    def orList = [
         QueryTemplate.AND(["account_id": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
         QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-    ] as List<Map<String, Object>>
+    ]
     result = ["searchCondition": QueryTemplate.OR(orList)]
 }

```

## 第 5 次修复

**错误信息：**
```
运行中... 
 扫描函数
运行日志
E-E.fx88888888.1000-62730679
StopWatch 'Scope_B3Z73__c': running time = 423 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

expecting '}', found 'result' @ line 14, column 5.
```

**代码变更（unified diff）：**
```diff
--- v4
+++ v5
@@ -11,6 +11,6 @@
         QueryTemplate.AND(["account_id": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
         QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-    ]
-    result = ["searchCondition": QueryTemplate.OR(orList)]
+    ] as List
+    result = ["searchCondition": QueryTemplate.OR(orList)] as Map<String, Object>
 }
 

```

## 第 6 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-34182880
StopWatch 'Scope_B3Z73__c': running time = 369 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List). Please check if the declared type is correct and if the method exists.
 @ line 14, column 34.
```

**代码变更（unified diff）：**
```diff
--- v5
+++ v6
@@ -8,8 +8,8 @@
 
 if (customerId) {
-    def orList = [
+    List<QueryTemplate> orList = [
         QueryTemplate.AND(["account_id": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
         QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-    ] as List
+    ] as List<QueryTemplate>
     result = ["searchCondition": QueryTemplate.OR(orList)] as Map<String, Object>
 }

```

