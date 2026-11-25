# 青屿港近岸测深交班

白班记录员把测深船的航次、校准批和原测条带登记到站库。质检发件员换算并筛选合格范围，发行与确切修订绑定的固定件。夜班凭中心库的实收号核定整段能否领用，缺少整段依据时把请求窗交还下一班复测。次日更正后，资料员仍可按原报告号查到当时使用的实收和原段。

## 运行

需要 Python 3.11 标准库和本地 SQLite。在项目根目录运行。

```sh
python3 -B check_project.py
python3 -B -m samples.demo
```

`check_project.py` 由控制台物化。直接运行同一套 unittest 可用 `python3 -B -m unittest discover -s tests -t .`。演示在临时目录建立站库和中心库，使用 `samples/day1.json` 和 `samples/day2.json`，并在核定前关闭站库。

## 一天的交班

1. 记录员提交测线 Q 的校准批 K、实际航次 A 和四条原段，生成工作修订。
2. 质检员把原段深度换算成毫米，保存每段合格、缺测或超限的状态。
3. 发件员选定该修订和 `[0,8)`，同次冻结修订与质控结果并存档原件。
4. 夜班中心实收实际收到的字节，取得可复用的实收号。
5. 夜班关闭站库，以指定实收号提交目标窗和可选的停用批。
6. `[0,6)` 由 A 的 `a1`、`a2` 接续覆盖，`[5,7)` 因 `a3` 缺测而待复测。`a4` 的 1200 mm 超出规则。
7. 中心同次提交可用窗口的报告和首执，报告写明实际用到的原段及各自覆盖。
8. 次日把 `a3` 更正为 1000 mm，另建修订、质控、发行并实收。
9. 新实收可签 `[5,7)`，旧实收对同窗仍待复测。资料员按前一日的报告号领取原报告与首执。

## Python 接口

站库和中心库使用两个 `sqlite3.Connection`。每次打开连接时启用 `PRAGMA foreign_keys = ON`。站库调用 `source.registration.init_source`、`quality.process.init_quality`、`issue.repository.init_issued_packets`，中心库调用 `intake.repository.init_intake`、`review.repository.init_reports`。初始化可重复执行，保留已存的工作修订、冻结记录、原件、实收和报告。初始化不装载样例。业务写入入口接收没有活动事务的连接，并负责自己的提交和回滚。仓储中的底层写入与冻结函数由其事务调用方协调。

| 业务 | 模块与入口 | 结果 |
| --- | --- | --- |
| 登记 | `source.registration.register(db, line, calibrations, passes, strips)` | 返回工作修订号。传入 `SurveyLine`、`CalibrationBatch`、`SurveyPass`、`RawStrip`。更正提交完整的新修订。 |
| 质控 | `quality.process.qualify(db, revision_id, rule)` | 返回 `Qualification`。工作版可重做，冻结版用 `load_qualification` 读取。 |
| 发行 | `issue.publish.publish(db, revision_id, window)` | 返回 `IssuedPacket`，含发行号和原件 `original`。用 `issue.repository.load_issued_packet` 按发行号重领。 |
| 实收 | `intake.receive.receive(db, original)` | 返回持久实收号。用 `intake.repository.get_accepted` 取得确切原件。 |
| 核定 | `review.sign.review(db, request)` | `ReviewRequest(receipt_id, window, suspended_batch=None)` 返回 `ReviewResult`。`signed` 含报告和首执，`resurvey` 的两项均为空。 |
| 领取 | `review.retrieve.retrieve(db, report_number)` | 返回存档 `(SignedReport, InitialReceipt)`。未知报告号抛出 `ReportMissing`。 |

`RawStrip(strip_id, pass_id, window, depth, unit)` 的 `depth` 接收十进制原测文本或显式 `None`。`MeterInterval(start, end)` 用整数米，允许负坐标，起点须小于终点。`QualityRule(min_mm, max_mm)` 用整数毫米闭区间。先按单位移动十进制小数点，再对半毫米远离零舍入。空读数保留缺测，合法零值参与阈值判断。同值异段分别保留。一个航次的校准批在本站固定，一个修订内的原段编号唯一。

登记关联错误抛出 `RegistrationError`。坏单位、坏读数、坏规则或冻结后重做质控抛出 `QualityError`。非法发行窗、没有有效质控结果、冻结或存档失败抛出 `PublishError`。首次发行失败保留工作态及原质控结果。

## 固定件与离线见证

同一发行编号序列由站库维护。V1 是 UTF-8 JSON，外层字段为 `version`、`issue_number`、`body`、`checksum`。`body` 重复绑定发行号，并提供 `line_id`、`revision_id`、`window` 与 `evidence`。`checksum` 是正文按键排序、紧凑分隔、ASCII 转义后的 JSON 字节的 SHA-256 十六进制值。用 `issue.envelope.encode_v1` 编码，`parse_v1` 读取。每项证据含 `pass_id`、`batch_id`、`strip_id`、裁入发行范围的 `window` 和原段的 `source_window`。原测值与不合格原因留站。

`receive` 在完整性核验后持久化原字节。同号同正文重收返回原实收号，保留首次字节。坏外层抛出 `PacketVerificationError`，校验有效的同号异件抛出 `PacketConflict`。核定阶段校验业务正文。`ReviewRequestError` 表示未知实收号、非法请求或错件。请求超出有效发行覆盖时返回待复测。停用批过滤该批的所有航次。一个未停用航次在请求窗内连续时可签，见证中的原段贡献依次覆盖整窗。多个合法航次可任选，当前实现按航次编号稳定遍历。

报告绑定实收号、发行号、实收正文校验值、修订号、请求窗、停用条件和选定航次。每个见证条目保留原段号、原段两端和实际使用的两端。`SigningError` 表示签存失败。本次报告及首执在同一事务内回滚，旧报告持久可领。
