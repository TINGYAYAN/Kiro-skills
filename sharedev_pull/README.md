# ShareDev 拉取/推送数据

由 `python -m fetcher.sharedev_client` 拉取或推送的租户元数据。

**多项目分目录**：按 `config.fxiaoke.project_name` 或 `--project` 分目录存储，互不覆盖。

每个项目文件夹包含该项目的全部元数据和需求相关文件：

| 路径 | 说明 |
|------|------|
| sharedev_pull/{项目}/objects.json | 对象列表 |
| sharedev_pull/{项目}/functions.json | APL 函数列表 |
| sharedev_pull/{项目}/.fields_cache/ | 字段缓存（payment_record__c.yml 等） |
| sharedev_pull/{项目}/objects_lookup.yml | 对象标签→api 映射（lookup_objects_for_req 输出） |
| sharedev_pull/{项目}/field_mappings.yml | 字段标签→api 映射（lookup_fields_for_req 输出） |
| sharedev_pull/{项目}/req.yml | 当前需求（执行 `pipeline.py --project {项目}` 时使用） |

拉取（默认按 config 项目名）：
```bash
cd _tools
python3 -m fetcher.sharedev_client --objects      # 保存到 sharedev_pull/硅基流动/objects.json
python3 -m fetcher.sharedev_client --functions    # 保存到 sharedev_pull/硅基流动/functions.json
```

多项目拉取：
```bash
python3 -m fetcher.sharedev_client --objects --project 硅基流动
python3 -m fetcher.sharedev_client --objects --project 中电长城
# 或指定输出路径：
python3 -m fetcher.sharedev_client --objects -o sharedev_pull/中电长城/objects.json
```

多项目证书配置（cert.conf）：
```ini
[sharedev.硅基流动]
domain = https://www.fxiaoke.com
cert = 证书A

[sharedev.中电长城]
domain = https://www.fxiaoke.com
cert = 证书B
```

推送：
```bash
python3 -m fetcher.sharedev_client --push Proc_XXX__c --file path/to/xxx.apl --commit "版本说明"
```
