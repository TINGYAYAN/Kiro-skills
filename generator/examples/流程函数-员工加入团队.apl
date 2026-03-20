/**
 * @author 纷享-曹树斌
 * @codeName 【流程】员工新建时加入T1分销商相关团队
 * @description 将【人员】的负责人，添加该【人员】<所属T1分销商>字段关联的【T1分销商】的相关团队、只读权限
 * @createTime 2025-11-20
 * @bindingObjectLabel 人员
 * @bindingObjectApiName PersonnelObj
 * @函数需求编号
 */

String personnelId = context.data["_id"] as String; // 人员ID
List ownerList = context.data["owner"] as List; // 负责人

if (ownerList != null && ownerList.size() > 0) {
  String ownerId = ownerList[0] as String; // 负责人ID
  String t1DistributorId = context.data["belonged_T1_distributor__c"] as String; // 所属T1分销商ID
  if (t1DistributorId != null) {
    // 添加相关团队
    def employTeamMember = TeamMemberAttribute.createEmployMember(
      [ownerId],
      TeamMemberEnum.Role.NORMAL_STAFF,
      TeamMemberEnum.Permission.READONLY
    )
    Fx.object.addTeamMember("AccountObj", t1DistributorId, employTeamMember).result()
  }
}