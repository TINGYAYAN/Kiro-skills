/**
 * @author 纷享实施人员
 * @codeName 【工作流】新建合同时自动创建回款计划
 * @description 新建合同时，根据合同金额和付款方式自动创建一条回款计划记录，并将回款计划关联到合同。
 * @createTime 2026-01-10
 * @bindingObjectLabel 合同
 * @bindingObjectApiName ContractObj
 * @函数需求编号
 */
String contractId = context.data["_id"] as String
String contractName = context.data["name"] as String
Object amount = context.data["contract_amount__c"]
String paymentType = context.data["payment_type__c"] as String

if (contractId == null || amount == null) {
    log.error("合同ID或金额为空，终止")
    return
}

// 查询合同负责人
def (Boolean findErr, QueryResult findResult, String findMsg) = Fx.object.find(
    "ContractObj",
    FQLAttribute.builder()
        .columns(["_id", "owner"])
        .queryTemplate(QueryTemplate.AND(["_id": QueryOperator.EQ(contractId)]))
        .build(),
    SelectAttribute.builder().build()
)

if (findErr) {
    log.error("查询合同失败：" + findMsg)
    return
}

List ownerList = null
if (findResult && findResult.size > 0 && findResult.dataList) {
    Map contractData = findResult.dataList[0] as Map
    ownerList = contractData["owner"] as List
}

// ✅ 正确写法：Fx.object.create 必须是 4 个参数，第3个是空 Map [:]，第4个是 CreateAttribute
def (Boolean createErr, Map createResult, String createMsg) = Fx.object.create(
    "PaymentPlanObj",
    [
        "name"          : contractName + "-回款计划",
        "contract__c"   : contractId,
        "plan_amount__c": amount,
        "payment_type__c": paymentType
    ] as Map<String, Object>,
    [:],
    CreateAttribute.builder().triggerWorkflow(false).build()
)

if (createErr) {
    log.error("创建回款计划失败：" + createMsg)
    return
}

String planId = createResult["_id"] as String
log.info("回款计划已创建：" + planId)

// ✅ 正确写法：Fx.object.update 必须是 4 个参数，第4个是 UpdateAttribute
// 注意：不要用 _ 作变量名，平台会报 warning，用真实变量名即使不用也不报错
def (Boolean updateErr, Map updateResult, String updateMsg) = Fx.object.update(
    "ContractObj",
    contractId,
    ["payment_plan__c": planId],
    UpdateAttribute.builder().triggerWorkflow(false).build()
)

if (updateErr) {
    log.error("回写合同回款计划失败：" + updateMsg)
} else {
    log.info("合同已关联回款计划")
}
