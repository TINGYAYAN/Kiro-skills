/**
 * 【按钮】打开SAP库存查询弹窗
 * 绑定对象：库存
 * 功能：点击按钮打开弹窗，接收查询条件后调用SAP接口查询并新增库存数据
 */

def openSAPQueryModal() {
    // 弹窗配置
    def modalConfig = [
        title: 'SAP库存查询',
        url: '/path/to/sap_inventory_modal.html',  // 替换为实际部署路径
        width: 500,
        height: 400,
        modal: true
    ]
    
    // 打开弹窗
    def result = openModal(modalConfig)
    
    if (result && result.action == 'querySubmit') {
        // 获取查询条件
        def queryParams = result.params
        
        // 调用SAP接口查询库存
        def sapResult = callSAPInventoryAPI(queryParams)
        
        if (sapResult.success && sapResult.data) {
            // 新增库存记录
            sapResult.data.each { item ->
                def newInventory = [
                    batch__c: item.batch,
                    material__c: item.material,
                    location__c: item.location,
                    serial_number__c: item.serialNumber,
                    quantity__c: item.quantity,
                    unit__c: item.unit
                ]
                
                // 创建库存记录
                def created = InventoryObj.create(newInventory)
                if (!created) {
                    log.error("新增库存记录失败: ${item}")
                }
            }
            
            showMessage('查询成功，已新增 ' + sapResult.data.size() + ' 条库存记录')
        } else {
            showMessage('查询失败: ' + sapResult.message, 'error')
        }
    }
}

/**
 * 调用SAP可用库存查询接口
 */
def callSAPInventoryAPI(queryParams) {
    try {
        // SAP接口配置
        def sapUrl = 'https://sap-api.example.com/inventory/query'
        def sapAuth = 'Bearer ' + getSAPToken()
        
        // 构建请求体
        def requestBody = [
            batch: queryParams.batch,
            material: queryParams.material,
            location: queryParams.location,
            serialNumber: queryParams.serialNumber
        ]
        
        // 调用HTTP接口
        def response = http.post(sapUrl, requestBody, [
            'Authorization': sapAuth,
            'Content-Type': 'application/json'
        ])
        
        if (response.statusCode == 200) {
            return [
                success: true,
                data: response.body.items ?: []
            ]
        } else {
            return [
                success: false,
                message: '接口返回错误: ' + response.statusCode
            ]
        }
    } catch (Exception e) {
        log.error('调用SAP接口异常', e)
        return [
            success: false,
            message: '调用接口异常: ' + e.message
        ]
    }
}

/**
 * 获取SAP认证token
 */
def getSAPToken() {
    // 从配置或缓存获取token
    // 实现方式根据SAP认证方式调整
    return 'your_sap_token_here'
}

// 执行主函数
openSAPQueryModal()
