/**
 * @codeName 自定义控制器-批量校验并返回明细
 * @description 对传入的明细 ID 列表做业务校验，返回校验通过/不通过的分组结果
 * @bindingObjectLabel --
 * @bindingObjectApiName NONE
 */

// 自定义控制器：参数通过变量名直接访问
// 示例入参：{ "detailIds": ["id1", "id2"] }

// ---------- 参数解析 ----------
Map req = (syncArg instanceof Map) ? (syncArg as Map) : [:]
List detailIds = (req["detailIds"] ?: []) as List

// ---------- 参数校验 ----------
if (detailIds.size() == 0) {
  return [
    "success": true,
    "data": ["passed": [], "failed": [], "hasFailed": false]
  ]
}

// ---------- 查询明细 ----------
def (Boolean error, QueryResult result, String errorMessage) = Fx.object.find(
  "TODO_DETAIL_OBJECT__c",            // TODO: 替换为实际明细对象 API 名
  FQLAttribute.builder()
    .columns(["_id", "name", "status__c"])   // TODO: 按需调整字段
    .queryTemplate(QueryTemplate.AND([
      "_id": QueryOperator.IN(detailIds)
    ]))
    .build(),
  SelectAttribute.builder().needInvalid(false).build()
)

if (error) {
  return ["success": false, "errorMessage": "查询明细失败: " + errorMessage]
}

List passed = []
List failed = []

(result?.dataList as List ?: []).each { item ->
  Map m = item as Map
  String id     = (m["_id"]    ?: "") as String
  String name   = (m["name"]   ?: "") as String
  String status = (m["status__c"] ?: "") as String

  // TODO: 替换为实际校验逻辑
  boolean ok = (status != "option_invalid__c")

  if (ok) {
    passed.add(["_id": id, "name": name])
  } else {
    failed.add(["_id": id, "name": name, "reason": "状态不符合要求: " + status])
  }
}

return [
  "success": true,
  "data": [
    "hasFailed": failed.size() > 0,
    "passed"   : passed,
    "failed"   : failed
  ]
]
