/**
 * @author 纷享-曹树斌
 * @codeName 【工作流】申领T2经销商
 * @description 1
 * @createTime 2026-02-26
 * @bindingObjectLabel T1及T2业务关系
 * @bindingObjectApiName t1_t2_business_relationship__c
 * @函数需求编号
 */
String objectId = context.data["_id"] as String
List currentOwner = context.data.owner as List
String companyName = context.data.t2_company_name__c as String
//根据T2公司名称查询【T2经销商】对象的公司名称
def (Boolean error, QueryResult result, String errorMessage) = Fx.object.find(
    "t2_dealer__c",
    FQLAttribute.builder()
        .columns(["_id", "name"])
        .queryTemplate(QueryTemplate.AND(["name": QueryOperator.EQ(companyName)]))
        .build(),
    SelectAttribute.builder()
        .build()
)

if (error) {
    log.error("查询失败，原因：" + errorMessage)
    return
}
log.info(result)

if (result && result.size > 0 && result.dataList) {
    String resultId = result.dataList[0]["_id"] as String
    
    Map updateT2Data = [
       "T2_dealer__c": resultId,
       "application_result__c":"option_application_successful__c"
    ]
    def (Boolean updateError, Map updateData, String updateErrorMessage) = Fx.object.update(
        "t1_t2_business_relationship__c", 
        objectId, 
        updateT2Data, 
        UpdateAttribute.builder()
            .triggerWorkflow(true)
            .build()
    )

    if (updateError) {
        log.error( updateErrorMessage)
    }
    if (currentOwner != null && currentOwner.size() > 0) {
        String ownerId = currentOwner[0] as String
        def teamAttr = TeamMemberAttribute.createEmployMember(
            [ownerId],
            TeamMemberEnum.Role.NORMAL_STAFF,
            TeamMemberEnum.Permission.READONLY
        )
        def (Boolean addTeamError, Object addTeamRes, String addTeamMsg) = Fx.object.addTeamMember(
            "t2_dealer__c",
            resultId,
            teamAttr
        )
        if (addTeamError) {
            log.error("添加团队成员失败：" + addTeamMsg)
        } else {
            log.info("成功将负责人添加到T2经销商团队中")
        }
    }
} else {
      def (Boolean updateError1, Map updateData1, String updateErrorMessage1) = Fx.object.update(
            "t1_t2_business_relationship__c", 
            objectId, 
            ["application_result__c": "option_no_data_found__c"], 
            UpdateAttribute.builder()
                .triggerWorkflow(true)
                .build()
        )
    }