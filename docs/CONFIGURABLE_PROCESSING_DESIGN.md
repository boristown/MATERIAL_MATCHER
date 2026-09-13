# 物料集团码匹配引擎：可配置数据处理与标准化设计（v2.3）

> 日期：2026-09-13  
> 状态：强制设计补丁。本文用于消除旧设计中“固定标准化流水线、全局文本空值、2% 默认数值容差”等硬编码风险。

## 1. 核心原则

底层只提供处理能力，不决定任何业务字段应该如何处理。

1. 核心引擎默认流水线仅为 `identity`，不改变原值；
2. 不得按字段名、客户名、物料类别自动启用标准号、尺寸、单位、同义词等规则；
3. 每条字段规则分别配置客户侧和集团侧处理流水线；
4. 流水线步骤严格按配置顺序执行，不得自动重排；
5. 原始值永久保留；
6. 每一步记录操作符、参数、输入和输出；
7. 任一可能改变或丢失语义的处理必须显式开启。

## 2. 运行模型

```text
原始值
  ↓
ProcessedValue(raw_value 永久保留)
  ↓
按方案加载有序处理流水线
  ↓
operator_1 → operator_2 → ...
  ↓
处理后值 + structured + trace
  ↓
FieldMatcher
```

```python
class ProcessedValue:
    raw_value: object
    value: object
    text: str | None
    value_type: str
    is_missing: bool
    structured: dict[str, object]
    trace: list[ProcessingTrace]

class ProcessingTrace:
    operator: str
    options: dict[str, object]
    input_preview: str
    output_preview: str
```

## 3. 处理操作符

第一阶段至少提供：

- `identity`：原样通过；唯一默认；
- `trim`：去首尾空格；
- `unicode_normalize`：Unicode 规范化；
- `width_map`：全角/半角映射；
- `case_map`：大小写转换；
- `whitespace_map`：空白映射；
- `punctuation_map`：标点映射；
- `nullify`：指定业务占位值转空；
- `synonym_map`：同义词映射；
- `regex_replace` / `regex_extract`；
- `substring`；
- `numeric_parse`；
- `unit_convert`；
- `dimension_parse`；
- `standard_code_parse`；
- `custom_plugin`。

任何操作符不得暗中启用其他操作符。

统一接口：

```python
class ProcessingOperator(Protocol):
    operator_id: str

    def apply(
        self,
        value: ProcessedValue,
        options: dict[str, object],
        context: ProcessingContext,
    ) -> ProcessedValue:
        ...
```

## 4. 流水线配置

```yaml
processing:
  pipelines:
    identity: []

    manufacturer_cn:
      - op: trim
      - op: synonym_map
        options:
          dictionary: manufacturer_aliases

    model_keep_case:
      - op: trim

    specification_cn:
      - op: width_map
        options:
          mode: configured_aliases
      - op: dimension_parse
        options:
          symbol_aliases:
            "Φ": "diameter"
            "φ": "diameter"
            "Ø": "diameter"
            "×": "multiply"
            "x": "multiply"
            "X": "multiply"
```

字段规则显式引用：

```yaml
rules:
  - id: specification
    source_pipeline: specification_cn
    target_pipeline: specification_cn
    matcher: numeric_dimension
```

未配置 pipeline 时使用 `identity`。

## 5. 空值规则

核心引擎只把数据源真实缺失视为缺失，例如：

- Excel 真正空单元格；
- CSV 缺失值；
- 数据库 `NULL`；
- Adapter 返回的 `None`。

下列文本不得全局视为空：

```text
NULL
<NULL>
N/A
-
/
88
999
无
不详
```

必须显式配置：

```yaml
- op: nullify
  options:
    values: ["88", "-"]
    match: exact
    case_sensitive: true
```

## 6. 标准号

`standard_code_parse` 是可选结构化解析器，不是固定标准化步骤。

建议解析并保留：

```json
{
  "raw": "GB/T 5133-1985",
  "family": "GB/T",
  "number": "5133",
  "part": null,
  "year": "1985",
  "suffix": null
}
```

年份、版本号、分部号不得在解析阶段丢失。是否忽略其中某部分必须由 matcher 显式配置，并写入解释信息。

## 7. 尺寸与规格

`dimension_parse` 是可选解析器。

`Φ/φ/Ø`、`x/X/×` 等是否等价，只能来自用户选择的模板或显式配置，不得写死到底层。

解析后应尽量结构化保存，例如：

```json
{
  "raw": "Φ10×50 mm",
  "dimensions": [
    {"role": "diameter", "value": 10, "unit": "mm"},
    {"role": "length", "value": 50, "unit": "mm"}
  ]
}
```

## 8. 数值容差

数值/尺寸 matcher 不得内置 2%、5% 或任何业务默认容差。

每条数值规则必须显式配置；缺失时报：

```text
NUMERIC_TOLERANCE_REQUIRED
```

支持：

```yaml
tolerance:
  mode: exact
```

```yaml
tolerance:
  mode: absolute
  value: 0.1
```

```yaml
tolerance:
  mode: relative
  value: 0.02
```

```yaml
tolerance:
  mode: range
  min_delta: -0.05
  max_delta: 0.10
```

容差属于字段规则，不属于系统全局参数。

## 9. Join 键

Join 键默认也使用 `identity`，不自动 trim、转换大小写或处理前导零。

```yaml
keys:
  - left: 物料
    right: MATNR
    left_pipeline: identity
    right_pipeline: identity
```

如需处理，左右键分别配置 pipeline。

## 10. Matcher 契约

Matcher 接收 `ProcessedValue`，而不是假定已经执行某套固定标准化的字符串。

```python
class FieldMatcher(Protocol):
    matcher_id: str

    def score(
        self,
        source_value: ProcessedValue,
        target_value: ProcessedValue,
        options: dict[str, object],
    ) -> FieldScore:
        ...
```

数值/尺寸 matcher 仅使用显式配置的解析结果和 tolerance；标准号 matcher 只有在显式使用 `standard_code_parse` 时才进行结构化比较。

## 11. UI 配置

字段对应表新增“数据处理”列。

默认显示“无处理”。点击后打开抽屉，分别配置客户侧和集团侧：

- 推荐模板（用户主动选择后才生效）；
- 有序处理步骤；
- 每一步参数；
- 上移/下移/删除；
- 原值 -> 处理后值预览；
- 完整 trace；
- 恢复 `identity`。

数值/尺寸规则在未配置 tolerance 时不得保存或发布。

## 12. 核心函数

```python
def apply_processing_pipeline(
    input_value: object,
    pipeline: CompiledProcessingPipeline,
    context: ProcessingContext,
) -> ProcessedValue:
    ...
```

必须严格按配置执行，不得根据客户、字段名、物料类别自动插入步骤。

## 13. API

配置界面需要预览接口：

```text
POST /api/profiles/{profile_id}/processing-preview
```

请求包含临时 pipeline 和样例 values；响应逐值返回原值、处理后值和 trace。接口只做预览，不修改正式数据。

新增错误码：

- `PROCESSING_OPERATOR_NOT_FOUND`；
- `PROCESSING_PIPELINE_INVALID`；
- `NUMERIC_TOLERANCE_REQUIRED`。

## 14. 推荐模板的边界

系统可以交付“文本基础、厂家名称、标准号、尺寸规格、单位数值”等推荐模板，但：

1. 用户主动选择才生效；
2. 发布时展开并保存实际操作符及参数；
3. 后续软件升级不得静默改变已发布 Profile；
4. 模板属于配置资产，不属于核心引擎行为。

## 15. 验收红线

出现以下任一情况即不符合通用匹配引擎设计：

1. 按客户名或字段名自动启用处理规则；
2. 核心引擎全局把 `NULL/N/A/-/88` 等文本当空值；
3. 固定 `trim → 全半角 → 大小写 → 标点 → 同义词` 顺序；
4. 尺寸符号等价关系写死在底层；
5. 标准号通过删除年份/版本来制造相等；
6. 数值规则存在隐式 2% 或其他默认容差；
7. 原始值被标准化结果覆盖；
8. 已发布 Profile 在软件升级后处理行为发生静默变化。
