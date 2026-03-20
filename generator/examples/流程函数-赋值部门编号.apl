/**
 * @author 田贤贤
 * @codeName 二期-【流程函数】赋值价目表创建人部门编号
 * @description 创建人部门编号和编码，自动取值为创建人所在主属的部门编号和对应的部门编码
 * @createTime 2025-09-08
 * @bindingObjectLabel 价目表
 * @bindingObjectApiName PriceBookObj
 * @函数需求编号
 */
 
String objectId = context.data["_id"] as String
List createdBy = context.data["created_by"] as List
String createdByStr = createdBy[0] as String

log.info("价目表ID: " + objectId)
log.info("创建人ID: " + createdByStr)

def (Boolean error, QueryResult result, String errorMessage) = Fx.object.find(
    "PersonnelObj",
    FQLAttribute.builder()
        .columns(["_id", "main_department"])
        .queryTemplate(QueryTemplate.AND(["_id": QueryOperator.EQ(createdByStr)]))
        .build(),
    SelectAttribute.builder()
        .build()
)

if (error) {
    log.error("查询人员对象失败，原因：" + errorMessage)
    return
}

log.info("人员对象查询结果: " + result)

if (result && result.size > 0 && result.dataList) {
    Map personnelData = result.dataList[0] as Map
    List main_department = personnelData["main_department"] as List
    String main_department_id = main_department[0] as String
    
    log.info("创建人主属部门ID: " + main_department_id)

    // 根据主属部门ID查询部门对象获取部门编码
    def (Boolean deptError, QueryResult deptResult, String deptErrorMessage) = Fx.object.find(
        "DepartmentObj",
        FQLAttribute.builder()
            .columns(["_id", "dept_id", "dept_code"])
            .queryTemplate(QueryTemplate.AND(["dept_id": QueryOperator.EQ(main_department_id)]))
            .build(),
        SelectAttribute.builder()
            .build()
    )

    if (deptError) {
        log.error("查询部门对象失败，原因：" + deptErrorMessage)
        return
    }

    log.info("部门对象查询结果: " + deptResult)

    if (deptResult && deptResult.size > 0 && deptResult.dataList) {
        Map departmentData = deptResult.dataList[0] as Map
        String dept_code = departmentData["dept_code"] as String
        
        log.info("部门编码: " + dept_code)

        def (Boolean error1, Map data1, String errorMessage1) = Fx.object.update(
            "PriceBookObj", 
            objectId, 
            [
                "creator_department_id__c": dept_code
            ], 
            UpdateAttribute.builder()
                .triggerWorkflow(true)
                .build()
        )

        if (error1) {
            log.error("更新价目表的创建人部门信息失败，原因：" + errorMessage1)
        } else {
            log.info("价目表的创建人部门信息已更新 - 部门ID：" + main_department_id + "，部门编码：" + dept_code)
        }
    } else {
        log.info("未找到匹配的部门记录，部门ID: " + main_department_id)
        def (Boolean error1, Map data1, String errorMessage1) = Fx.object.update(
            "PriceBookObj", 
            objectId, 
            ["creator_department_id__c": main_department_id], 
            UpdateAttribute.builder()
                .triggerWorkflow(true)
                .build()
        )

        if (error1) {
            log.error("更新价目表的创建人部门编号失败，原因：" + errorMessage1)
        } else {
            log.info("价目表的创建人部门编号已更新为：" + main_department_id + "（未找到对应部门编码）")
        }
    }
} else {
    log.info("未找到创建人记录，用户ID: " + createdByStr)
}
