/**
 * @author 纷享实施人员
 * @codeName 【范围规则】关联字段按类型过滤
 * @description 范围规则函数：根据当前记录的某字段值，限制关联字段的可选范围
 * @createTime 2025-03-01
 * @bindingObjectLabel 客户
 * @bindingObjectApiName AccountObj
 */

// 范围规则函数：通过 context.data 获取当前表单数据（含未保存值）
// return 包含 searchCondition 的 Map 以过滤关联字段可选记录；return [:] 表示不限制

String typeValue = (context.data["type__c"] ?: "") as String

if (typeValue == "typeA") {
  return [
    "searchCondition": QueryTemplate.AND([
      "type__c": QueryOperator.EQ("typeA")
    ])
  ]
}

if (typeValue == "typeB") {
  return [
    "searchCondition": QueryTemplate.AND([
      "type__c": QueryOperator.EQ("typeB")
    ])
  ]
}

// 获取不到类型时显示全部
return [:]
