# APL 修复报告：【范围规则】任务明细.本次联系人

生成时间：2026-03-25 00:08:01

共修复 6 次

## 第 1 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-4982422
StopWatch 'Scope_6xZaa__c': running time = 252 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 23, column 28.
```

**代码变更（unified diff）：**
```diff
--- v0
+++ v1
@@ -10,6 +10,4 @@
  * @函数需求编号
  */
-// 待确认：联系人对象中「客户姓名」关联字段的 API 名，参考历史示例推断为 account__c，需在平台对象管理中核实
-// 注意：QueryTemplate.OR 在部分场景需额外开通，若保存报错请改用下方多分支写法
 
 String customerId = context.data.customer__c as String
@@ -21,12 +19,14 @@
 if (customerId && agentId) {
     return [
-        "searchCondition": QueryTemplate.OR([
-            QueryTemplate.AND([
-                "account__c": QueryOperator.EQ(customerId),
-                "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
-            ]),
-            QueryTemplate.AND([
-                "agent__c": QueryOperator.EQ(agentId),
-                "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
+        "searchCondition": QueryTemplate.AND([
+            QueryTemplate.OR([
+                QueryTemplate.AND([
+                    "account__c": QueryOperator.EQ(customerId),
+                    "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
+                ]),
+                QueryTemplate.AND([
+                    "agent__c": QueryOperator.EQ(agentId),
+                    "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
+                ])
             ])
         ])

```

## 第 2 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-33184417
StopWatch 'Scope_6xZaa__c': running time = 402 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 13.
[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#AND(java.util.List ). Please check if the declared type 
```

**代码变更（unified diff）：**
```diff
--- v1
+++ v2
@@ -21,14 +21,8 @@
         "searchCondition": QueryTemplate.AND([
             QueryTemplate.OR([
-                QueryTemplate.AND([
-                    "account__c": QueryOperator.EQ(customerId),
-                    "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
-                ]),
-                QueryTemplate.AND([
-                    "agent__c": QueryOperator.EQ(agentId),
-                    "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
-                ])
-            ])
-        ])
+                QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
+                QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
+            ] as List<Object>)
+        ] as List<Object>)
     ]
 }
@@ -36,8 +30,5 @@
 if (customerId) {
     return [
-        "searchCondition": QueryTemplate.AND([
-            "account__c": QueryOperator.EQ(customerId),
-            "contact_type__c": QueryOperator.EQ("option_customer_contact__c")
-        ])
+        "searchCondition": QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>)
     ]
 }
@@ -45,8 +36,5 @@
 if (agentId) {
     return [
-        "searchCondition": QueryTemplate.AND([
-            "agent__c": QueryOperator.EQ(agentId),
-            "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")
-        ])
+        "searchCondition": QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
     ]
 }

```

## 第 3 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-59885703
StopWatch 'Scope_6xZaa__c': running time = 247 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 13.
[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#AND(java.util.List ). Please check if the declared type 
```

**代码变更（unified diff）：**
```diff
--- v2
+++ v3
@@ -23,6 +23,6 @@
                 QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
                 QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-            ] as List<Object>)
-        ] as List<Object>)
+            ] as List<QueryTemplate>)
+        ] as List<QueryTemplate>)
     ]
 }

```

## 第 4 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-84301969
StopWatch 'Scope_6xZaa__c': running time = 393 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 13.
[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#AND(java.util.List ). Please check if the declared type 
```

**代码变更（unified diff）：**
```diff
--- v3
+++ v4
@@ -18,12 +18,8 @@
 
 if (customerId && agentId) {
-    return [
-        "searchCondition": QueryTemplate.AND([
-            QueryTemplate.OR([
-                QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>),
-                QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-            ] as List<QueryTemplate>)
-        ] as List<QueryTemplate>)
-    ]
+    QueryTemplate customerCond = QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>)
+    QueryTemplate agentCond = QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
+    QueryTemplate orCond = QueryTemplate.OR([customerCond, agentCond] as List<QueryTemplate>)
+    return ["searchCondition": QueryTemplate.AND([orCond] as List<QueryTemplate>)]
 }
 

```

## 第 5 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-79900482
StopWatch 'Scope_6xZaa__c': running time = 370 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 28.
[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#AND(java.util.List ). Please check if the declared type 
```

**代码变更（unified diff）：**
```diff
--- v4
+++ v5
@@ -20,6 +20,6 @@
     QueryTemplate customerCond = QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>)
     QueryTemplate agentCond = QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-    QueryTemplate orCond = QueryTemplate.OR([customerCond, agentCond] as List<QueryTemplate>)
-    return ["searchCondition": QueryTemplate.AND([orCond] as List<QueryTemplate>)]
+    QueryTemplate orCond = QueryTemplate.OR([customerCond, agentCond])
+    return ["searchCondition": QueryTemplate.AND([orCond])]
 }
 

```

## 第 6 次修复

**错误信息：**
```
运行脚本 
 扫描函数
运行日志
E-E.fx88888888.1000-23022189
StopWatch 'Scope_6xZaa__c': running time = 441 ms
---------------------------------------------
ms % Task name
---------------------------------------------


返回值:
 APL代码fix error Action
错误提示

[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#OR(java.util.List ). Please check if the declared type is correct and if the method exists.
 @ line 22, column 28.
[Static type checking] - Cannot find matching method com.fxiaoke.functions.model.QueryTemplate#AND(java.util.List ). Please check if the declared type 
```

**代码变更（unified diff）：**
```diff
--- v5
+++ v6
@@ -20,6 +20,6 @@
     QueryTemplate customerCond = QueryTemplate.AND(["account__c": QueryOperator.EQ(customerId), "contact_type__c": QueryOperator.EQ("option_customer_contact__c")] as Map<String, Object>)
     QueryTemplate agentCond = QueryTemplate.AND(["agent__c": QueryOperator.EQ(agentId), "contact_type__c": QueryOperator.EQ("option_agent_contact_person__c")] as Map<String, Object>)
-    QueryTemplate orCond = QueryTemplate.OR([customerCond, agentCond])
-    return ["searchCondition": QueryTemplate.AND([orCond])]
+    QueryTemplate orCond = QueryTemplate.OR([customerCond, agentCond] as List<QueryTemplate>)
+    return ["searchCondition": QueryTemplate.AND([orCond] as List<QueryTemplate>)]
 }
 

```

