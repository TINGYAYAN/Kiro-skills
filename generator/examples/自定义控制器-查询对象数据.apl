/**
 * @codeName 自定义控制器-查询对象数据
 * @description 根据传入的 ID 列表查询对象记录，返回结构化结果
 * @bindingObjectLabel --
 * @bindingObjectApiName NONE
 */

// 自定义控制器：参数通过变量名直接访问（由调用方传入）
// 示例入参：{ "recordIds": ["id1", "id2"], "objectApiName": "AccountObj" }

// ---------- 参数解析 ----------
Map req = (syncArg instanceof Map) ? (syncArg as Map) : [:]

List recordIds = (req["recordIds"] ?: []) as List
String objectApiName = (req["objectApiName"] ?: "") as String

// ---------- 参数校验 ----------
if (!objectApiName) {
  return ["success": false, "errorMessage": "objectApiName 不能为空"]
}
if (recordIds.size() == 0) {
  return ["success": true, "data": ["total": 0, "dataList": []]]
}

// ---------- 查询 ----------
def (Boolean error, QueryResult result, String errorMessage) = Fx.object.find(
  objectApiName,
  FQLAttribute.builder()
    .columns(["_id", "name"])          // TODO: 按需调整返回字段
    .queryTemplate(QueryTemplate.AND([
      "_id": QueryOperator.IN(recordIds)
    ]))
    .build(),
  SelectAttribute.builder()
    .needInvalid(false)
    .build()
)

if (error) {
  return ["success": false, "errorMessage": "查询失败: " + errorMessage]
}

List dataList = result?.dataList as List ?: []
List output = []
dataList.each { item ->
  Map m = item as Map
  output.add([
    "_id" : (m["_id"] ?: ""),
    "name": (m["name"] ?: "")
    // TODO: 补充其他需要返回的字段
  ])
}

return [
  "success": true,
  "data": [
    "total"   : dataList.size(),
    "dataList": output
  ]
]
