/**
 * @author 纷享实施人员
 * @codeName 【计划任务】定时查询批量处理模板
 * @description 计划任务由调度触发，无当前流程记录；禁止依赖 context.data，须自行 FQL 查询后处理。
 * @createTime 2026-03-24
 * @bindingObjectLabel 客户
 * @bindingObjectApiName AccountObj
 */
// ----- 1. 计划任务入口（无 context.data，勿当流程函数写）-----
log.info("[业务] 计划任务开始")

long now = System.currentTimeMillis()
long windowStart = now - (24L * 60 * 60 * 1000)

// ----- 2. 查询待处理数据（条件/对象/字段按需求与字段表替换）-----
def (Boolean findErr, QueryResult findResult, String findMsg) = Fx.object.find(
    "AccountObj",
    FQLAttribute.builder()
        .columns(["_id", "name"])
        .queryTemplate(QueryTemplate.AND([
            "create_time": QueryOperator.GTE(windowStart)
        ]))
        .limit(100)
        .build(),
    SelectAttribute.builder().build()
)
if (findErr) {
    log.error("[业务] 查询失败: " + findMsg)
    return
}
List dataList = findResult?.dataList as List
if (dataList == null || dataList.size() == 0) {
    log.info("[业务] 无待处理数据")
    return
}
log.info("[业务] 待处理条数: " + dataList.size())

// ----- 3. 逐条处理（条数大时优先 batchCreate/batchUpdate，见系统 prompt）-----
dataList.each { Object item ->
    Map row = item as Map
    String rid = row["_id"] as String
    if (!rid) {
        return  // each 闭包内用 return 代替 continue
    }
    log.info("[业务] 处理记录 _id=" + rid)
}

log.info("[业务] 计划任务结束")
