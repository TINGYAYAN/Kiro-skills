/**
 * @codeName 自定义控制器-调用第三方接口
 * @description 接收前端参数，调用外部 HTTP 接口，返回结构化结果
 * @bindingObjectLabel --
 * @bindingObjectApiName NONE
 */
import com.fxiaoke.functions.http.Request
import com.fxiaoke.functions.http.StringBody
import com.fxiaoke.functions.http.HttpResult

// ---------- 参数解析 ----------
Map req = (syncArg instanceof Map) ? (syncArg as Map) : [:]

String targetId = (req["id"] ?: "") as String   // TODO: 按需调整入参字段

if (!targetId) {
  return ["success": false, "errorMessage": "id 不能为空"]
}

// ---------- 获取 Token（复用公共函数） ----------
Map tokenInfo = GetAccessToken.getAccessToken()
if (!tokenInfo || !tokenInfo["accessToken"]) {
  return ["success": false, "errorMessage": "获取 accessToken 失败"]
}

// ---------- 构建请求 ----------
String GW_URL = "https://example.com/api/your-endpoint"   // TODO: 替换为实际 URL

Map requestBody = [
  "code": "F_FX_EXAMPLE",    // TODO: 替换为实际接口编码
  "data": [
    "id": targetId
    // TODO: 补充其他请求字段
  ]
]

StringBody body = StringBody.builder().content(Fx.json.toJson(requestBody)).build()
Request request = Request.builder()
  .method("POST")
  .url(GW_URL)
  .timeout(15000)
  .retryCount(1)
  .header("Content-Type", "application/json")
  .header("accessToken", tokenInfo["accessToken"] as String)
  .body(body)
  .build()

// ---------- 执行请求 ----------
def httpResult = Fx.http.execute(request)
if (!httpResult || httpResult.size() < 2 || httpResult[1] == null) {
  String errMsg = (httpResult?.size() > 2 ? httpResult[2] : "未知错误") as String
  return ["success": false, "errorMessage": "HTTP 请求失败: " + errMsg]
}

HttpResult result = httpResult[1] as HttpResult
if (result.statusCode != 200) {
  return ["success": false, "errorMessage": "HTTP 状态码异常: " + result.statusCode]
}

// ---------- 解析响应 ----------
Map resp = [:]
try {
  String content = result.content as String
  if (content?.trim()?.startsWith("{") || content?.trim()?.startsWith("[")) {
    resp = Fx.json.parse(content) as Map
  } else {
    return ["success": false, "errorMessage": "响应非 JSON: " + content?.take(200)]
  }
} catch (Exception e) {
  return ["success": false, "errorMessage": "响应解析失败: " + e.getMessage()]
}

log.info("第三方响应: " + Fx.json.toJson(resp))

// ---------- 业务判断 ----------
String flag = (resp["flag"] ?: resp["success"]) as String
String msg  = (resp["msg"]  ?: resp["message"] ?: "") as String

if ("true".equalsIgnoreCase(flag) || "success".equalsIgnoreCase(flag)) {
  return ["success": true, "data": resp["data"] ?: [:], "message": msg]
} else {
  return ["success": false, "errorMessage": "接口返回失败: " + (msg ?: "未知错误")]
}
