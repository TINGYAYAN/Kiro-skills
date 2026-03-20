/**
 * @author 田贤贤
 * @codeName 二期-【UI函数】报价单业务组织默认值
 * @description 给业务组织字段赋值为当前登录用户的所属组织
 * @createTime 2025-09-12
 * @bindingObjectLabel 报价单
 * @bindingObjectApiName QuoteObj
 * @函数需求编号
 */

// 获取当前登录用户信息
log.info("完整上下文信息: " + context)
log.info("当前对象数据: " + context.data)

// 从当前对象数据中获取创建者信息
def currentUserId = context.data.created_by
log.info("当前用户ID: " + currentUserId)

// 处理用户ID格式（可能是数组格式）
String userId = null
if (currentUserId) {
    if (currentUserId instanceof List) {
        List userList = currentUserId as List
        if (userList.size() > 0) {
            userId = userList.get(0) as String
        }
    } else {
        userId = currentUserId as String
    }
    log.info("处理后的用户ID: " + userId)
}


UIEvent event = UIEvent.build(context) {
}

// 直接根据当前用户查询对应的业务组织记录并设置
String userOrganization = null

if (userId && userId.trim() != "") {
    log.info("开始查询用户记录，用户ID: " + userId)
    
    // 第一步：查询人员对象，获取用户的所属组织
    def (Boolean error1, QueryResult personnelResult, String errorMessage1) = Fx.object.find(
        "PersonnelObj",
        FQLAttribute.builder()
            .columns(["_id", "field_8dLi1__c"])
            .queryTemplate(QueryTemplate.AND(["_id": QueryOperator.EQ(userId)]))
            .build(),
        SelectAttribute.builder()
            .build()
    )
    
    if (error1) {
        log.error("查询人员对象失败: " + errorMessage1)
    } else {
        log.info("人员对象查询结果: " + personnelResult)
        
                if (personnelResult && personnelResult.size > 0 && personnelResult.dataList) {
                    Map personnelData = personnelResult.dataList[0] as Map
                    String organizationId = personnelData["field_8dLi1__c"] as String
                    
                    log.info("找到人员信息，所属组织ID: " + organizationId)
                    
                    if (organizationId && organizationId.trim() != "") {
                        // 第二步：根据组织ID查询业务组织对象，获取name
                        log.info("开始查询业务组织对象，组织ID: " + organizationId)
                        
                        def (Boolean error2, QueryResult orgResult, String errorMessage2) = Fx.object.find(
                            "object_business_organization__c",
                            FQLAttribute.builder()
                                .columns(["_id", "name"])
                                .queryTemplate(QueryTemplate.AND(["_id": QueryOperator.EQ(organizationId)]))
                                .build(),
                            SelectAttribute.builder()
                                .build()
                        )
                        
                        if (error2) {
                            log.error("查询业务组织对象失败: " + errorMessage2)
                        } else {
                            log.info("业务组织对象查询结果: " + orgResult)
                            
                            if (orgResult && orgResult.size > 0 && orgResult.dataList) {
                                Map orgData = orgResult.dataList[0] as Map
                                userOrganization = orgData["name"] as String
                                log.info("找到业务组织名称: " + userOrganization)
                            } else {
                                log.info("未找到业务组织记录，组织ID: " + organizationId)
                            }
                        }
                    } else {
                        log.info("用户所属组织ID为空")
                    }
                } else {
                    log.info("未找到用户记录，用户ID: " + userId)
                }
    }
}

if (userOrganization && userOrganization.trim() != "") {
    log.info("设置业务组织名称: " + userOrganization)
    log.info("当前对象字段 - business_organization__c: " + context.data.business_organization__c)
    log.info("当前对象字段 - business_organization_name__c: " + context.data.business_organization_name__c)
    
    event = UIEvent.build(context) {
        editMaster("business_organization_name__c": userOrganization)
        editMasterFields "business_organization_name__c" readOnly(false) hidden(false) required(false)
    }
    
    log.info("UIEvent构建完成，设置business_organization_name__c = " + userOrganization)
} else {
    log.info("无法获取用户所属组织信息")
    event = UIEvent.build(context) {
    }
}

log.info("业务组织默认值设置完成")
return event
