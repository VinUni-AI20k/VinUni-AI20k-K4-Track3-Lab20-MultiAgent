# Lab 20 — Multi-Agent Research System: Giải thích chi tiết & Hướng dẫn triển khai từng bước

> Tài liệu này đọc toàn bộ repo (`src/`, `tests/`, `configs/`, `docs/`, `notebooks/`, `ai_agent_offline_research_corpus_v2/`, `pyproject.toml`, `Makefile`, `Dockerfile`, CI/pre-commit) và giải thích: (1) bài lab thực chất đang yêu cầu điều gì, (2) các file liên kết với nhau ra sao, (3) triển khai từng bước từ đầu đến cuối, và (4) với mỗi chỗ cần sửa — **tại sao** nó là một quyết định thiết kế học viên phải tự đưa ra và **thay đổi ra sao** để đúng tinh thần "production-grade".

---

## 1. Bài lab này thực sự đang yêu cầu điều gì?

Đây **không phải** là một bài lab "điền code vào chỗ trống theo hướng dẫn có sẵn". Đọc `README.md` và `docs/lab_guide.md` cho thấy rõ chủ đích:

> "Mục tiêu của repo này là cung cấp **production-grade skeleton** để học viên phát triển code cá nhân. Các phần logic quan trọng được để ở dạng `TODO` để học viên tự triển khai."

Nói cách khác: **kiến trúc, hợp đồng interface (contracts), schema, và guardrail đã được thiết kế sẵn** (đây là phần "production-grade" — tách lớp rõ ràng, dùng Pydantic, có config qua env var, có test, có CI). Phần học viên phải tự làm là **các quyết định logic** — quyết định nào chỉ con người thiết kế hệ thống mới trả lời được:

- Supervisor nên điều phối theo chính sách nào?
- Researcher nên lấy nguồn ở đâu, lọc thế nào?
- Khi nào dừng, khi nào retry, khi nào fallback?
- Chất lượng multi-agent hơn single-agent ở điểm nào, đánh đổi ra sao?

30 vị trí đánh dấu `TODO(student)` (xác nhận bằng `grep -R "TODO(student)" -n src tests docs`) chính là các quyết định đó, được cố ý để **raise `StudentTodoError`** thay vì để trống hay có sẵn code sai — nghĩa là chương trình sẽ **crash có kiểm soát và có thông điệp rõ ràng** cho tới khi học viên implement, thay vì âm thầm chạy sai.

### "Xong" bài lab nghĩa là gì?

Theo `README.md` mục Deliverables + `CONTRIBUTING.md`, một lần nộp bài hoàn chỉnh gồm:

1. Repo cá nhân (fork/branch riêng) với toàn bộ `TODO(student)` trong `src/` đã được thay bằng implementation thật.
2. `make lint`, `make typecheck`, `make test` chạy sạch.
3. Screenshot trace hoặc link trace (LangSmith/Langfuse/JSON trace tự dựng).
4. `reports/benchmark_report.md` so sánh single-agent vs multi-agent bằng số liệu thật.
5. Một đoạn giải thích failure mode gặp phải và cách fix.
6. `docs/design_template.md` được điền đầy đủ (không còn TODO).

Phần còn lại của tài liệu này đi từng bước để đạt được 6 mục trên.

---

## 2. Kiến trúc mục tiêu và luồng dữ liệu

```text
                     User Query (CLI: --query "...")
                              │
                              ▼
                    ResearchQuery (Pydantic, validate)
                              │
                              ▼
                    ResearchState (single source of truth)
                              │
                              ▼
                 ┌── Supervisor / Router ──┐
                 │   (đọc state, quyết      │
                 │    định route tiếp theo) │
                 └──────────┬───────────────┘
        ┌────────────┬──────┴───────┬─────────────┐
        ▼            ▼              ▼              ▼
  Researcher     Analyst         Writer          done
 (search →      (notes →       (notes →      (dừng vòng
  sources +      analysis_      final_         lặp, trả
  research_      notes)         answer)         state)
  notes)
        │            │              │
        └──────┬─────┴──────┬───────┘
               ▼             ▼
         state.trace   state.agent_results
               │
               ▼
     Observability (log/span) + Evaluation (benchmark, report)
```

Vòng lặp **Supervisor → Worker → Supervisor → ... → done** là bản chất của một *router pattern* (một trong các pattern được liệt kê trong `A03` của corpus offline: "Pattern 4: supervisor with dynamic spawning"). Mỗi lượt, Supervisor nhìn vào `ResearchState` hiện tại (đã có gì, thiếu gì) để quyết định worker kế tiếp — đây chính là lý do `ResearchState` được thiết kế là **single source of truth** duy nhất truyền qua tất cả các agent, thay vì mỗi agent giữ state riêng.

---

## 3. Bản đồ toàn bộ repository — file nào làm gì, liên kết ra sao

| File | Vai trò | Phụ thuộc vào | Được dùng bởi | Trạng thái |
|---|---|---|---|---|
| [`core/schemas.py`](../src/multi_agent_research_lab/core/schemas.py) | Định nghĩa `AgentName`, `ResearchQuery`, `AgentResult`, `SourceDocument`, `BenchmarkMetrics` — **hợp đồng dữ liệu** dùng xuyên suốt hệ thống | — (nền tảng) | mọi module khác | Đã xong |
| [`core/state.py`](../src/multi_agent_research_lab/core/state.py) | `ResearchState` — state chia sẻ giữa các agent, có `record_route()`, `add_trace_event()` | `core/schemas.py` | `agents/*`, `graph/workflow.py`, `evaluation/*`, `cli.py` | Đã xong (khung), học viên có thể mở rộng field |
| [`core/config.py`](../src/multi_agent_research_lab/core/config.py) | `Settings` (Pydantic Settings) đọc `.env`; `get_settings()` cache singleton | `pydantic-settings` | `cli.py`, (nên được) `services/llm_client.py`, `agents/supervisor.py` | Đã xong |
| [`core/errors.py`](../src/multi_agent_research_lab/core/errors.py) | `LabError`, `StudentTodoError`, `AgentExecutionError`, `ValidationError` | — | mọi skeleton method | Đã xong |
| [`agents/base.py`](../src/multi_agent_research_lab/agents/base.py) | `BaseAgent` — interface `run(state) -> state` bắt buộc mọi agent tuân theo | `core/state.py` | tất cả agent | Đã xong |
| [`agents/supervisor.py`](../src/multi_agent_research_lab/agents/supervisor.py) | Router: quyết định agent kế tiếp | `agents/base.py`, `core/state.py` | `graph/workflow.py` | **TODO** |
| [`agents/researcher.py`](../src/multi_agent_research_lab/agents/researcher.py) | Thu thập nguồn, viết `research_notes` | `services/search_client.py` (nên gọi) | `graph/workflow.py` | **TODO** |
| [`agents/analyst.py`](../src/multi_agent_research_lab/agents/analyst.py) | Phân tích `research_notes` → `analysis_notes` | `services/llm_client.py` (nên gọi) | `graph/workflow.py` | **TODO** |
| [`agents/writer.py`](../src/multi_agent_research_lab/agents/writer.py) | Tổng hợp → `final_answer` kèm citation | `services/llm_client.py` (nên gọi) | `graph/workflow.py`, `cli.py` (in kết quả) | **TODO** |
| [`agents/critic.py`](../src/multi_agent_research_lab/agents/critic.py) | (Bonus) fact-check, chấm citation coverage, phát hiện hallucination | tương tự trên | `graph/workflow.py` (tuỳ chọn) | **TODO**, tuỳ chọn |
| [`graph/workflow.py`](../src/multi_agent_research_lab/graph/workflow.py) | Lắp ráp toàn bộ agent thành một graph có thể chạy (`build()`/`run()`) | tất cả `agents/*`, `core/state.py` | `cli.py` | **TODO** |
| [`services/llm_client.py`](../src/multi_agent_research_lab/services/llm_client.py) | Abstraction gọi LLM (`complete()` → `LLMResponse`) | `core/errors.py` | `agents/analyst.py`, `agents/writer.py`, `agents/critic.py`, `cli.py` (baseline) | **TODO** |
| [`services/search_client.py`](../src/multi_agent_research_lab/services/search_client.py) | Abstraction tìm kiếm nguồn (`search()` → `list[SourceDocument]`) | `core/schemas.py` | `agents/researcher.py` | **TODO** |
| [`services/storage.py`](../src/multi_agent_research_lab/services/storage.py) | `LocalArtifactStore` — ghi file report/trace vào `reports/` | — | `evaluation/*`, `cli.py` (nếu cần export) | Đã xong |
| [`evaluation/benchmark.py`](../src/multi_agent_research_lab/evaluation/benchmark.py) | `run_benchmark()` đo latency, khung để thêm quality/cost/citation/failure | `core/schemas.py`, `core/state.py` | `notebooks/`, script benchmark của học viên | Khung có sẵn, cần **mở rộng** |
| [`evaluation/report.py`](../src/multi_agent_research_lab/evaluation/report.py) | `render_markdown_report()` → markdown table | `core/schemas.py` | script benchmark, `reports/benchmark_report.md` | Khung có sẵn, cần **mở rộng** |
| [`observability/logging.py`](../src/multi_agent_research_lab/observability/logging.py) | `configure_logging()` | `logging` (stdlib) | `cli.py` | Đã xong |
| [`observability/tracing.py`](../src/multi_agent_research_lab/observability/tracing.py) | `trace_span()` context manager, khung span tối giản | `time` | `agents/*` (nên bọc quanh `run()`), `graph/workflow.py` | Khung có sẵn, cần **tích hợp/nâng cấp** |
| [`utils/timer.py`](../src/multi_agent_research_lab/utils/timer.py) | `elapsed_timer()` tiện ích đo thời gian | — | `evaluation/benchmark.py` hoặc tuỳ chọn | Đã xong |
| [`cli.py`](../src/multi_agent_research_lab/cli.py) | Entry point Typer: lệnh `baseline`, `multi-agent` | mọi module trên | người dùng cuối / `Makefile` / `Dockerfile` | `baseline` là placeholder cứng, `multi-agent` gọi graph |
| [`configs/lab_default.yaml`](../configs/lab_default.yaml) | Model + temperature cho từng agent, danh sách query benchmark mẫu | — | **chưa có code nào đọc file này** | Cần học viên tự viết loader |
| [`.env.example`](../.env.example) | Template biến môi trường | ↔ khớp 1-1 với field trong `core/config.py::Settings` | `.env` thật của học viên | Đã xong |
| [`tests/test_agents_todo.py`](../tests/test_agents_todo.py) | "Canary test" xác nhận skeleton còn nguyên TODO | `agents/supervisor.py` | CI | Sẽ **chủ động FAIL** sau khi implement — phải thay thế |
| [`tests/test_state.py`, `test_config.py`, `test_report.py`](../tests) | Test hành vi phần đã xong sẵn | `core/*`, `evaluation/report.py` | CI | Giữ nguyên, dùng làm tham chiếu style test |
| [`notebooks/demo_multi_agent_walkthrough.ipynb`](../notebooks/demo_multi_agent_walkthrough.ipynb) | Sandbox prototype nhanh, không cần API key (dùng Mock) | `core/*` | — (không import vào `src/`) | Nơi nên bắt đầu code trước khi đưa vào `src/` |
| [`ai_agent_offline_research_corpus_v2/`](../ai_agent_offline_research_corpus_v2/) | 30 file JSON kiến thức offline, có citation ID rõ ràng | — | **nên** được `services/search_client.py` đọc làm nguồn mock/offline | Dữ liệu có sẵn, tận dụng ra sao là quyết định của học viên |
| `.github/workflows/ci.yml`, `.pre-commit-config.yaml` | Lint + format + test tự động | `pyproject.toml` (ruff/mypy config) | GitHub Actions, git hook | Đã xong |

### Nguyên tắc luồng import (một chiều, không vòng lặp phụ thuộc)

```
core/  ←── agents/  ←── graph/  ←── cli.py
core/  ←── services/ ←── agents/
core/  ←── evaluation/
        ←── observability/ (độc lập, cắm vào bất kỳ đâu cần log/trace)
```

`core/` không import bất kỳ thứ gì từ `agents/`, `services/`, `graph/` — đây là quy tắc kiến trúc phải giữ khi implement: **agent không được tự ý import SDK của OpenAI/Tavily trực tiếp**, mà luôn đi qua `services/llm_client.py` / `services/search_client.py`. Đây là lý do file `llm_client.py` có docstring: *"Production note: agents should depend on this interface instead of importing an SDK directly."* — nhờ vậy, muốn đổi provider (OpenAI → Azure OpenAI → Anthropic) chỉ cần sửa một file, không phải sửa từng agent.

---

## 4. Nguyên lý thiết kế xuyên suốt phải tuân thủ khi implement

Từ `README.md` mục "Quy ước production trong repo", đối chiếu với code hiện tại:

| Quy ước | Đã thể hiện ở đâu trong skeleton | Học viên cần giữ nguyên khi thêm code |
|---|---|---|
| Tách rõ `agents/services/core/graph/evaluation/observability` | Cấu trúc thư mục | Không nhét business logic (gọi LLM, gọi search) trực tiếp vào `graph/workflow.py` hay `cli.py` |
| Không hard-code API key | `core/config.py` dùng `pydantic-settings` đọc `.env` | Trong `services/llm_client.py`, lấy key qua `get_settings().openai_api_key`, **không** `os.environ["OPENAI_API_KEY"]` rải rác |
| Input/output dùng Pydantic schema | `ResearchQuery`, `AgentResult`, `SourceDocument`, `BenchmarkMetrics` | Field mới thêm vào `ResearchState` phải có type hint + default hợp lý (Pydantic sẽ validate) |
| Type hints, lint, format, test | `pyproject.toml`: `ruff strict select`, `mypy strict = true` | Code mới phải có type hint đầy đủ — `mypy strict` sẽ fail nếu thiếu |
| Logging/tracing từ đầu | `observability/logging.py`, `observability/tracing.py` | Mỗi `agent.run()` nên log ít nhất 1 dòng + 1 `trace_span` |
| Không chạy vô hạn | `Settings.max_iterations`, `Settings.timeout_seconds` (đã có field, chưa được dùng ở đâu) | `SupervisorAgent` **bắt buộc** phải đọc `settings.max_iterations` và so với `state.iteration` |
| Benchmark report thay vì chỉ demo | `evaluation/benchmark.py`, `evaluation/report.py` | Phải thật sự ghi ra `reports/benchmark_report.md` |

---

## 5. Bước 0 — Chuẩn bị môi trường

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev,llm]"
cp .env.example .env
```

**Tại sao có 2 nhóm optional-dependencies (`dev`, `llm`) trong `pyproject.toml`?**
`dev` (pytest, ruff, mypy, pre-commit) cần cho *mọi* lần chạy để lint/test. `llm` (openai, langgraph, langchain-core, langsmith) chỉ cần khi thật sự implement phần gọi model/orchestration thật — tách ra để ai chỉ muốn đọc/chạy test không bị bắt buộc cài SDK nặng.

Điền `.env` — mỗi biến ánh xạ trực tiếp 1-1 vào field của `Settings` trong `core/config.py` (khớp qua `validation_alias`):

| Biến trong `.env` | Field trong `Settings` | Bắt buộc? |
|---|---|---|
| `OPENAI_API_KEY` | `openai_api_key` | Chỉ khi dùng OpenAI thật; nếu dùng offline corpus + mock LLM thì có thể để trống khi prototype trong notebook |
| `OPENAI_MODEL` | `openai_model` (default `gpt-4o-mini`) | Không |
| `LANGSMITH_API_KEY`, `LANGSMITH_PROJECT` | tracing tuỳ chọn | Không |
| `TAVILY_API_KEY` | `tavily_api_key` | Không nếu dùng corpus offline làm nguồn tra cứu |
| `MAX_ITERATIONS`, `TIMEOUT_SECONDS` | guardrail | Nên giữ default (6, 60s) trừ khi có lý do |

Chạy smoke test:

```bash
make test
python -m multi_agent_research_lab.cli --help
```

**Lưu ý cho Windows:** `make` **không có sẵn** trên Windows/Git Bash mặc định (verify thật: `which make` → *"make: not found"*) — `Makefile` chỉ là lớp vỏ mỏng gọi thẳng các lệnh bên dưới, nên có thể chạy trực tiếp mà không cần cài `make`:

| Thay vì | Chạy lệnh trực tiếp |
|---|---|
| `make install` | `pip install -e ".[dev,llm]"` |
| `make test` | `pytest` |
| `make lint` | `ruff check src tests` |
| `make format` | `ruff format src tests` |
| `make typecheck` | `mypy src` |
| `make run-baseline` | `python -m multi_agent_research_lab.cli baseline --query "..."` |
| `make run-multi` | `python -m multi_agent_research_lab.cli multi-agent --query "..."` |

Muốn dùng `make` đúng như README/CONTRIBUTING mô tả thì cài qua Chocolatey (`choco install make`), Scoop, hoặc chạy trong WSL — nhưng không bắt buộc, bảng lệnh trực tiếp ở trên tương đương 100%.

Ở thời điểm này `pytest` sẽ **PASS** (vì `test_agents_todo.py` đang test đúng hành vi hiện tại: `SupervisorAgent().run()` phải raise `StudentTodoError`).

---

## 6. Bước 1 — Baseline single-agent

**File:** `cli.py` (`baseline()`), `services/llm_client.py`

### Tại sao phải làm baseline trước tiên?

Hai lý do liên kết trực tiếp với `docs/lab_guide.md`:

1. Quy tắc "Không thêm agent nếu không có lý do rõ ràng" chỉ có thể được *chứng minh* nếu có một baseline single-agent để so sánh — nếu không có baseline, mọi tuyên bố "multi-agent tốt hơn" chỉ là cảm tính.
2. `evaluation/benchmark.py::run_benchmark` nhận một `Runner = Callable[[str], ResearchState]` — baseline chính là runner đầu tiên cần có để benchmark có ý nghĩa.

### Cách làm — `services/llm_client.py`

`LLMClient.complete()` hiện raise `StudentTodoError`. Đây là **một điểm hội tụ** duy nhất mà cả `cli.py::baseline`, `AnalystAgent`, `WriterAgent`, `CriticAgent` đều sẽ gọi vào — nên implement kỹ ở đây một lần, tránh lặp code retry/timeout ở từng agent (đúng docstring "Keep retry, timeout, and token logging here rather than inside agents").

```python
# services/llm_client.py
from dataclasses import dataclass
from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from multi_agent_research_lab.core.config import get_settings


@dataclass(frozen=True)
class LLMResponse:
    content: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


# Giá tham khảo (USD / 1K token) — tách riêng để dễ cập nhật, không hard-code trong logic
_PRICE_PER_1K = {"gpt-4o-mini": {"input": 0.00015, "output": 0.0006}}


class LLMClient:
    def __init__(self) -> None:
        settings = get_settings()
        self._model = settings.openai_model
        self._client = OpenAI(api_key=settings.openai_api_key)

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=8))
    def complete(self, system_prompt: str, user_prompt: str) -> LLMResponse:
        response = self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            timeout=get_settings().timeout_seconds,
        )
        usage = response.usage
        price = _PRICE_PER_1K.get(self._model, {"input": 0.0, "output": 0.0})
        cost = None
        if usage is not None:
            cost = (usage.prompt_tokens / 1000) * price["input"] + (
                usage.completion_tokens / 1000
            ) * price["output"]
        return LLMResponse(
            content=response.choices[0].message.content or "",
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
            cost_usd=cost,
        )
```

**Tại sao dùng `tenacity` ở đây?** `tenacity>=8.3` đã nằm sẵn trong `dependencies` chính (không phải `dev`/`llm`) của `pyproject.toml` — đây là gợi ý ẩn của người ra đề rằng retry/backoff là bắt buộc, không tuỳ chọn, vì LLM API có thể rate-limit hoặc timeout ngẫu nhiên; nếu không retry, một request lỗi mạng sẽ làm cả benchmark run fail oan.

### Cách làm — `cli.py::baseline`

```python
@app.command()
def baseline(query: Annotated[str, typer.Option("--query", "-q", ...)]) -> None:
    _init()
    request = _parse_query(query)
    state = ResearchState(request=request)
    llm = LLMClient()
    response = llm.complete(
        system_prompt=(
            "You are a research assistant. Answer directly and concisely; "
            "do not fabricate sources."
        ),
        user_prompt=request.query,
    )
    state.final_answer = response.content
    state.agent_results.append(
        AgentResult(agent=AgentName.WRITER, content=response.content,
                     metadata={"mode": "single_agent_baseline",
                               "input_tokens": response.input_tokens,
                               "output_tokens": response.output_tokens})
    )
    console.print(Panel.fit(state.final_answer, title="Single-Agent Baseline"))
```

**Vì sao đổi từ chuỗi cứng sang gọi LLM thật?** Placeholder cũ (`"Baseline skeleton response..."`) tồn tại chỉ để CLI không crash khi chưa cài gì — một khi `LLMClient` đã hoạt động, chuỗi cứng này không còn phản ánh baseline thật, và benchmark so với nó sẽ vô nghĩa (latency ≈ 0, quality không đo được).

---

## 7. Bước 2 — Search client & dùng kho dữ liệu offline làm nguồn nghiên cứu

**File:** `services/search_client.py`, thư mục `ai_agent_offline_research_corpus_v2/`

### Tại sao đây là bước nên làm sớm, và tại sao dùng corpus offline?

`docs/lab_guide.md` có hẳn một mục troubleshooting về lỗi SSL khi gọi Tavily/OpenAI qua HTTPS trên macOS — cho thấy người ra đề **biết trước** việc phụ thuộc vào một search API thật (Tavily) trong một lab 2 giờ có rủi ro: cần API key riêng, có thể bị rate-limit, kết quả tìm kiếm thay đổi theo thời gian (benchmark không tái lập được), và lỗi môi trường (SSL) làm mất thời gian debug không liên quan tới bài học.

Thư mục `ai_agent_offline_research_corpus_v2/` (30 file JSON, mỗi file ~90KB, có `README.md` + `SCHEMA.json` riêng) được thiết kế đúng để giải quyết việc này: nó là "**self-contained offline knowledge corpus**" với hướng dẫn rành mạch (`offline_usage_instructions`): *"Disable browser/web-search tools. Give the system one JSON topic file and allow retrieval only inside that file. Require the final report to cite embedded `source_id` or `article_id` values."*

Mỗi topic (ví dụ topic 1 — *"Single-Agent vs Multi-Agent Architectures for Complex Research Tasks"*, trùng chủ đề chính của bài lab) chứa:

- `knowledge_articles` (7 bài, có `article_id`) — nội dung dài, có thể dùng làm "trang tài liệu" để trích snippet.
- `source_documents` (9 nguồn, có `document_id`/`citation_label`, `is_synthetic` để phân biệt nguồn thật (`autogen`, `metagpt`, `anthropic_agents`, `agentbench`, `llm_agents_blog`, `gaia`) và nguồn tổng hợp giả lập (`T0X-SYN-*`) — cực kỳ hữu ích để dạy học viên phân biệt "nguồn có trọng số cao/thấp" khi Analyst đánh giá bằng chứng.
- `fact_bank` (≥30 atomic fact có `evidence_source_ids`) — dùng làm ground truth để tính `citation_coverage`.

**Dùng corpus này làm `SearchClient` mang lại 3 lợi ích trực tiếp cho benchmark của bài lab:**

1. **Tái lập được (reproducible)** — không phụ thuộc mạng/API rate-limit, benchmark chạy nhiều lần cho kết quả ổn định để so sánh.
2. **Có citation ID rõ ràng** (`source_id`, `article_id`) — khớp hoàn hảo với field `SourceDocument.url` (có thể set `url=None`, dùng `metadata={"source_id": ...}`) và với metric `citation_coverage` trong `BenchmarkMetrics`.
3. **Không cần `TAVILY_API_KEY`** — loại bỏ một điểm phụ thuộc ngoại vi trong buổi lab 2 giờ.

### Cách làm (implementation thật, đã chạy và verify)

`services/search_client.py` nạp toàn bộ 30 file JSON thành một danh sách `SourceDocument` phẳng (480 document: 7 `knowledge_articles` + 9 `source_documents` × 30 topic), cache bằng `@lru_cache` (cùng pattern với `core.config.get_settings`), rồi xếp hạng theo số lần token của query xuất hiện trong `title + snippet`:

```python
# services/search_client.py (rút gọn — xem file thật để đầy đủ)
import json, logging, re
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

from multi_agent_research_lab.core.errors import AgentExecutionError
from multi_agent_research_lab.core.schemas import SourceDocument

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {"a", "an", "the", "of", "in", "on", "for", "to", "and", "or", ...}
_DEFAULT_CORPUS_DIR = (
    Path(__file__).resolve().parents[3] / "ai_agent_offline_research_corpus_v2" / "topics"
)


def _tokenize(text: str) -> list[str]:
    return [w for w in _WORD_RE.findall(text.lower()) if len(w) > 2 and w not in _STOPWORDS]


class SearchClient:
    def __init__(self, corpus_dir: Path | None = None) -> None:
        self._corpus_dir = corpus_dir or _DEFAULT_CORPUS_DIR
        self._documents = _load_corpus(self._corpus_dir)  # tuple, cached

    def search(self, query: str, max_results: int = 5) -> list[SourceDocument]:
        terms = _tokenize(query)
        scored = sorted(
            ((_score(doc, terms), doc) for doc in self._documents),
            key=lambda pair: pair[0], reverse=True,
        )
        top = scored[:max_results]
        return [
            doc.model_copy(update={"metadata": {**doc.metadata, "match_score": score}})
            for score, doc in top
        ]


def _score(doc: SourceDocument, terms: list[str]) -> int:
    if not terms:
        return 0
    counts = Counter(_tokenize(f"{doc.title} {doc.snippet}"))
    return sum(counts[t] for t in terms)


@lru_cache(maxsize=8)
def _load_corpus(corpus_dir: Path) -> tuple[SourceDocument, ...]:
    if not corpus_dir.is_dir():
        raise AgentExecutionError(f"Offline research corpus not found at {corpus_dir}.")
    documents: list[SourceDocument] = []
    for topic_file in sorted(corpus_dir.glob("*.json")):
        data: dict[str, Any] = json.loads(topic_file.read_text(encoding="utf-8"))
        kb, topic_name = data["knowledge_base"], data["topic"]["name"]
        for article in kb["knowledge_articles"]:
            documents.append(SourceDocument(
                title=f"{topic_name} - {article['title']}", url=None,
                snippet=article["content"][:500],
                metadata={"kind": "knowledge_article", "article_id": article["article_id"],
                          "topic_file": topic_file.name, "is_synthetic": False},
            ))
        for source in kb["source_documents"]:
            documents.append(SourceDocument(
                title=source["title"], url=source.get("provenance_url"),
                snippet=source["full_text"][:500],
                metadata={"kind": "source_document", "source_id": source["document_id"],
                          "topic_file": topic_file.name, "is_synthetic": source["is_synthetic"]},
            ))
    return tuple(documents)
```

**5 quyết định thiết kế đáng giải thích trong bản thật (khác bản nháp ban đầu):**

1. **`@lru_cache` trên `_load_corpus`, không phải trên `SearchClient` object** — vì `ResearcherAgent` có thể tạo `SearchClient()` mới mỗi lần `run()` (một instance nhẹ), nhưng việc *đọc + parse 30 file JSON* mới là phần tốn thời gian (~0.6-0.7s thực đo) — tách cache ra hàm module-level để chi phí đó chỉ trả đúng 1 lần cho toàn bộ process, dù `SearchClient` được khởi tạo bao nhiêu lần (benchmark chạy nhiều query sẽ tạo nhiều instance).
2. **`doc.model_copy(update=...)` thay vì gán `doc.metadata["match_score"] = score`** — vì `_documents` là **tuple dùng chung, cache toàn cục**; nếu mutate trực tiếp object đã cache, lần `search()` sau (với query khác) sẽ đọc phải `match_score` cũ do lần gọi trước để lại — một lỗi state-sharing kinh điển khi cache đối tượng mutable. `model_copy` (Pydantic v2) tạo bản sao mới, giữ cache gốc bất biến.
3. **`match_score` trong metadata thay vì lọc cứng "top-k theo ngưỡng"** — để lại tín hiệu độ tin cậy cho tầng sau (Analyst/Critic/benchmark) tự quyết định, thay vì `SearchClient` tự ý quyết định "đủ liên quan hay không" — đúng nguyên tắc tách trách nhiệm.
4. **Tokenize bằng regex `[a-z0-9]+` + bỏ từ ≤2 ký tự + stopword list, thay vì `str.split()` + substring `in`** — đây là một **bug thật phát hiện khi test**: bản đầu dùng `haystack.count(term)` (đếm substring) khiến một truy vấn hoàn toàn không liên quan như `"best pizza recipe in Naples"` vẫn ra điểm 17-19, vì các từ ngắn (`"in"`) khớp substring bên trong hàng trăm từ dài khác (`"coordination"`, `"considering"`, ...). Sau khi đổi sang so khớp theo *token nguyên từ* (`Counter` trên danh sách token đã tokenize, không phải substring), truy vấn không liên quan tụt xuống điểm ~1, còn truy vấn đúng chủ đề (`"multi-agent research task decomposition coordination overhead"`) vẫn giữ điểm 10-12 — đúng như kỳ vọng.
5. **Không raise lỗi khi không tìm thấy gì liên quan** — `search()` luôn trả về `max_results` document tốt nhất có thể (best-effort), chỉ ghi `logger.warning` khi điểm cao nhất bằng 0; guard "nguồn rỗng" trong `ResearcherAgent` (mục 9.1) do đó chủ yếu phòng trường hợp *corpus rỗng/không đọc được*, không phải trường hợp "không khớp từ khoá" — đây là khác biệt quan trọng cần ghi rõ trong `design_template.md`.

**Vì sao không dùng vector search/embedding ở đây?** Bài lab giới hạn 2 giờ và trọng tâm là *orchestration*, không phải *retrieval quality*; keyword scoring theo token đã đủ để Researcher có nguồn hợp lý để trích dẫn. Nếu muốn nâng cao (bonus), có thể thay bằng embedding + cosine similarity mà không đổi interface `search()`.

---

## 8. Bước 3 — Supervisor / Router

**File:** `agents/supervisor.py`

### Tại sao đây là "trái tim" của bài lab

Chính notebook (`## 4. Supervisor Routing`) gọi thẳng đây là *"trái tim của bài lab — bạn tự thiết kế policy"*. Đây cũng là tiêu chí đầu tiên trong `docs/peer_review_rubric.md` ("Role clarity") và câu hỏi thiết kế trong `lab_guide.md`:

> Khi nào gọi Researcher? Khi nào gọi Analyst? Khi nào gọi Writer? Khi nào stop? Nếu agent fail thì retry hay fallback?

### Cách làm

```python
# agents/supervisor.py
from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.config import get_settings
from multi_agent_research_lab.core.state import ResearchState

NEXT_RESEARCHER = "researcher"
NEXT_ANALYST = "analyst"
NEXT_WRITER = "writer"
DONE = "done"


class SupervisorAgent(BaseAgent):
    name = "supervisor"

    def run(self, state: ResearchState) -> ResearchState:
        settings = get_settings()
        route = self._decide(state, settings.max_iterations)
        state.record_route(route)               # tăng state.iteration, ghi route_history
        state.add_trace_event("supervisor.route", {"next": route, "iteration": state.iteration})
        return state

    def _decide(self, state: ResearchState, max_iterations: int) -> str:
        # Guardrail #1: chặn vòng lặp vô hạn — luôn kiểm tra đầu tiên
        if state.iteration >= max_iterations:
            return DONE

        # Guardrail #2: fallback khi worker trước đó lỗi — bỏ qua bước phân tích,
        # đi thẳng tới Writer để vẫn trả lời được (degraded nhưng không "chết")
        if state.errors and state.research_notes and not state.final_answer:
            return NEXT_WRITER

        # Chính sách chính: điều phối theo field nào trong state còn thiếu
        if not state.sources:
            return NEXT_RESEARCHER
        if not state.analysis_notes:
            return NEXT_ANALYST
        if not state.final_answer:
            return NEXT_WRITER
        return DONE
```

**Tại sao dùng state-field-driven routing (thay vì LLM tự quyết định route)?** Đây là một lựa chọn thiết kế đáng nói rõ trong `docs/design_template.md`: routing dựa trên field nào của `ResearchState` đã có/thiếu là **deterministic**, dễ test (không cần mock LLM để test routing), rẻ (không tốn token gọi LLM chỉ để quyết định "đi đâu tiếp"), và dễ debug qua `route_history`. Đánh đổi: kém linh hoạt hơn một router LLM có thể quay lại Researcher nếu Analyst phát hiện thiếu bằng chứng — đây chính là điểm học viên nên bàn ở mục "Routing policy" trong `design_template.md`, và là hướng nâng cao hợp lý (ví dụ: nếu `AnalystAgent` phát hiện bằng chứng yếu thì ghi cờ `state.errors` để Supervisor route lại về Researcher, thay vì đi thẳng Writer).

**Vì sao guardrail max_iterations phải là dòng kiểm tra đầu tiên?** Vì mọi nhánh khác đều có thể (do lỗi implement) không bao giờ đạt điều kiện `done` — đặt guard trước cùng đảm bảo vòng lặp *luôn* có điểm dừng cứng, độc lập với logic nghiệp vụ bên dưới.

**Đã implement và verify thật** (code trên khớp gần như nguyên văn với `agents/supervisor.py` thật): chạy `SupervisorAgent` lặp lại trên một `ResearchState` không bao giờ được worker nào cập nhật (mô phỏng trường hợp xấu nhất — mọi worker đều "treo"/lỗi im lặng) cho ra `route_history = ['researcher', 'researcher', 'researcher', 'researcher', 'researcher', 'researcher', 'done']` — dừng đúng ở lần lặp thứ 7 (`max_iterations=6` mặc định), xác nhận guardrail hoạt động độc lập với việc worker có chạy đúng hay không.

Vì `SupervisorAgent.run()` giờ trả về route thật thay vì raise `StudentTodoError`, test canary `tests/test_agents_todo.py` đã **FAIL đúng như thiết kế** — đã xoá và thay bằng `tests/test_supervisor.py` (7 test case: 4 nhánh routing chính, guardrail max-iterations, guardrail fallback khi có lỗi, và trace event) ngay tại bước này thay vì đợi tới Bước 8 (§13) — vì để một test biết-trước-sẽ-fail nằm trong repo dù chỉ tạm thời sẽ làm `make test`/CI đỏ oan.

---

## 9. Bước 4 — Worker agents: Researcher, Analyst, Writer, (Critic)

**File:** `agents/researcher.py`, `agents/analyst.py`, `agents/writer.py`, `agents/critic.py`

Cả 4 file đều theo cùng một khuôn: đọc field input từ `state`, gọi service tương ứng, ghi field output + `AgentResult` + trace event. Notebook (`## 3. Demo Agents`) đã viết sẵn `DemoResearcherAgent` làm mẫu — nguyên tắc chuyển thẳng sang `src/`.

### 9.1 `ResearcherAgent` — tại sao & cách làm

**Tại sao:** đây là agent duy nhất chạm vào thế giới bên ngoài (qua `SearchClient`); mọi agent sau nó chỉ làm việc trên dữ liệu nó thu thập — nên chất lượng lọc nguồn ở đây quyết định trần chất lượng của toàn hệ thống.

```python
# agents/researcher.py
from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.search_client import SearchClient


class ResearcherAgent(BaseAgent):
    name = "researcher"

    def __init__(self, search_client: SearchClient | None = None) -> None:
        self.search_client = search_client or SearchClient()

    def run(self, state: ResearchState) -> ResearchState:
        docs = self.search_client.search(
            state.request.query, max_results=state.request.max_sources
        )
        if not docs:
            state.errors.append("researcher: no sources found")
            state.add_trace_event("researcher.error", {"reason": "empty_results"})
            return state

        state.sources = docs
        state.research_notes = "\n".join(f"- {d.title}: {d.snippet}" for d in docs)
        state.agent_results.append(
            AgentResult(agent=AgentName.RESEARCHER, content=state.research_notes,
                        metadata={"num_sources": len(docs)})
        )
        state.add_trace_event("researcher.done", {"num_sources": len(docs)})
        return state
```

**Vì sao có guard `if not docs`?** Đây chính là cơ chế nuôi guardrail "fallback" của Supervisor ở bước 8 — nếu Researcher không tìm được gì, nó **không raise exception** (sẽ làm sập cả graph) mà ghi vào `state.errors` và trả state về; Supervisor sẽ đọc `state.errors` để quyết định fallback thay vì để hệ thống crash.

### 9.2 `AnalystAgent` — tại sao & cách làm

**Tại sao:** tách riêng khỏi Writer để có một bước *chuyển đổi bằng chứng thô → luận điểm có cấu trúc* độc lập, kiểm chứng được — đúng tinh thần "structured artifacts" mà corpus offline nhấn mạnh nhiều lần (`fact K014`: *"Structured artifacts make state and ownership easier to inspect than a single growing chat transcript"*). Nếu gộp Analyst vào Writer, prompt sẽ phải làm 2 việc cùng lúc (phân tích + hành văn), khó kiểm soát và khó test riêng từng phần.

```python
# agents/analyst.py
from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

_SYSTEM_PROMPT = (
    "You are a research analyst. Given research notes, extract key claims, "
    "compare viewpoints, and flag weak or unsupported evidence. Be concise."
)


class AnalystAgent(BaseAgent):
    name = "analyst"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        if not state.sources:
            state.errors.append("analyst: no sources to analyze")
            return state

        response = self.llm_client.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=f"Research notes:\n{state.research_notes}",
        )
        state.analysis_notes = response.content
        state.agent_results.append(
            AgentResult(agent=AgentName.ANALYST, content=response.content,
                        metadata={"input_tokens": response.input_tokens,
                                  "output_tokens": response.output_tokens})
        )
        state.add_trace_event("analyst.done", {})
        return state
```

### 9.3 `WriterAgent` — tại sao & cách làm

**Tại sao bắt buộc citation:** `docs/peer_review_rubric.md` không có tiêu chí "văn phong hay", nhưng `evaluation` cần đo được `citation_coverage` (`BenchmarkMetrics.citation_coverage`) — nếu Writer không được yêu cầu trích dẫn tường minh, metric này không thể tính được từ text tự do. Vì vậy prompt phải **ép buộc format trích dẫn** thay vì hy vọng model tự làm.

```python
# agents/writer.py
from multi_agent_research_lab.agents.base import BaseAgent
from multi_agent_research_lab.core.schemas import AgentName, AgentResult
from multi_agent_research_lab.core.state import ResearchState
from multi_agent_research_lab.services.llm_client import LLMClient

_SYSTEM_PROMPT = (
    "You are a technical writer. Write a clear final answer for the given "
    "audience. You MUST cite sources inline as [1], [2], ... matching the "
    "numbered source list provided, and MUST NOT invent facts not present "
    "in the notes or sources."
)


class WriterAgent(BaseAgent):
    name = "writer"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        context = state.analysis_notes or state.research_notes or ""
        source_list = "\n".join(
            f"[{i}] {s.title} ({s.url or s.metadata.get('source_id', 'n/a')})"
            for i, s in enumerate(state.sources, start=1)
        )
        response = self.llm_client.complete(
            system_prompt=_SYSTEM_PROMPT,
            user_prompt=(
                f"Audience: {state.request.audience}\n"
                f"Query: {state.request.query}\n\nNotes:\n{context}\n\n"
                f"Sources:\n{source_list}"
            ),
        )
        state.final_answer = response.content
        state.agent_results.append(
            AgentResult(agent=AgentName.WRITER, content=response.content,
                        metadata={"input_tokens": response.input_tokens,
                                  "output_tokens": response.output_tokens})
        )
        state.add_trace_event("writer.done", {})
        return state
```

**Vì sao `context = state.analysis_notes or state.research_notes`?** Đây chính là cách Writer "sống sót" khi Supervisor fallback thẳng từ Researcher sang Writer (bỏ qua Analyst do lỗi) — Writer luôn có nội dung để viết, kể cả trong đường lỗi.

### 9.4 `CriticAgent` (tuỳ chọn/bonus) — tại sao & cách làm

**Tại sao là bonus chứ không bắt buộc:** thêm một agent kiểm chứng độc lập đúng là khuyến nghị mạnh của corpus offline (`fact K008`: *"A verifier is strongest when it uses an independent evidence path"*), nhưng nó tăng số lượt gọi LLM (chi phí + latency) — đúng tension "specialization vs coordination overhead" mà corpus nhấn mạnh. Việc để tuỳ chọn buộc học viên phải tự cân nhắc đánh đổi này thay vì mặc định "càng nhiều agent càng tốt" — đúng quy tắc đầu tiên của `lab_guide.md`: *"Không thêm agent nếu không có lý do rõ ràng."*

```python
# agents/critic.py
class CriticAgent(BaseAgent):
    name = "critic"

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    def run(self, state: ResearchState) -> ResearchState:
        if not state.final_answer:
            state.errors.append("critic: no final_answer to review")
            return state
        response = self.llm_client.complete(
            system_prompt=(
                "You are a fact-checking critic. List any claim in the answer "
                "not supported by the provided sources, and any missing citation."
            ),
            user_prompt=f"Answer:\n{state.final_answer}\n\nSources:\n"
                        + "\n".join(s.title for s in state.sources),
        )
        state.agent_results.append(
            AgentResult(agent=AgentName.CRITIC, content=response.content)
        )
        state.add_trace_event("critic.done", {})
        return state
```

Nếu bật Critic, Supervisor cần thêm một nhánh route mới (ví dụ route `critic` sau `writer`, trước `done`) — đây là lý do `AgentName.CRITIC` đã có sẵn trong enum dù `CriticAgent` là optional: schema đã chừa chỗ, quyết định *dùng hay không* thuộc về học viên.

### Đã implement và verify thật cả 4 agent (chạy chuỗi thủ công, chưa qua `graph/workflow.py`)

Vì `MultiAgentWorkflow` ở Bước 5 chưa được lắp, 4 agent được test bằng cách gọi tay tuần tự `Researcher → Analyst → Writer → Critic` trên cùng một `ResearchState`, với query thật `"task decomposition and coordination overhead in multi-agent research systems"` (cố tình chọn để trúng đúng nội dung corpus offline):

- **Researcher**: lấy đúng 3 nguồn liên quan nhất từ corpus (`match_score` 13/11/11, đúng 2 trong 3 nguồn là bài viết về chủ đề "Single-Agent vs Multi-Agent Architectures").
- **Analyst**: trích ra "Key Claims" có cấu trúc bullet, đúng như prompt yêu cầu.
- **Writer**: viết câu trả lời cuối, **có trích dẫn `[1]`, `[2]` đúng format** như thiết kế.
- **Critic**: đây là phát hiện đáng chú ý nhất — Critic **bắt được lỗi trích dẫn thật** trong output của Writer: *"Source [3] is listed but never cited."* — chứng minh giá trị thực tế của agent kiểm chứng độc lập (đúng insight `fact K008` của corpus), dù nó tốn thêm ~1 lệnh gọi LLM.
- Tổng chi phí 4 agent cho 1 query: **$0.00059** (tính từ `cost_usd` tích luỹ trong `agent_results`) — số liệu này chính là input cho benchmark so sánh cost single-agent vs multi-agent ở Bước 7 (§12).

---

## 10. Bước 5 — Lắp ráp `graph/workflow.py` (LangGraph)

### Tại sao dùng LangGraph thay vì vòng `while True` viết tay

Notebook đã cho chạy được một vòng lặp thủ công (`run_demo_workflow`, mục 5) — điều đó **đủ để prototype**, nhưng không đủ "production-grade" vì thiếu: khả năng visualize graph, checkpointing (lưu/khôi phục state giữa các bước), interrupt/human-in-the-loop, và tích hợp sẵn với LangSmith tracing (`pyproject.toml` đã kéo theo `langsmith>=0.1` trong nhóm `llm`). Đây là lý do `README.md` References trỏ thẳng tới LangGraph concepts docs, và tại sao `graph/workflow.py` tách biệt hẳn khỏi `agents/` (docstring: *"Keep orchestration here; keep agent internals in `agents/`"*) — tách để có thể thay LangGraph bằng framework khác (hoặc while-loop) mà không đụng vào logic từng agent.

### Cách làm (implementation thật, đã chạy trên `langgraph==1.2.11`)

```python
# graph/workflow.py
from typing import Any

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from multi_agent_research_lab.agents.analyst import AnalystAgent
from multi_agent_research_lab.agents.researcher import ResearcherAgent
from multi_agent_research_lab.agents.supervisor import (
    DONE, NEXT_ANALYST, NEXT_RESEARCHER, NEXT_WRITER, SupervisorAgent,
)
from multi_agent_research_lab.agents.writer import WriterAgent
from multi_agent_research_lab.core.state import ResearchState

_SUPERVISOR = "supervisor"


class MultiAgentWorkflow:
    def __init__(
        self,
        supervisor: SupervisorAgent | None = None,
        researcher: ResearcherAgent | None = None,
        analyst: AnalystAgent | None = None,
        writer: WriterAgent | None = None,
    ) -> None:
        # Constructor injection: production dùng default (agent thật); test
        # truyền agent đã wire sẵn fake search/LLM client (§13).
        self._supervisor = supervisor or SupervisorAgent()
        self._workers = {
            NEXT_RESEARCHER: researcher or ResearcherAgent(),
            NEXT_ANALYST: analyst or AnalystAgent(),
            NEXT_WRITER: writer or WriterAgent(),
        }
        self._graph = self.build()

    def build(self) -> CompiledStateGraph[Any, Any, Any, Any]:
        builder = StateGraph(ResearchState)
        builder.add_node(_SUPERVISOR, self._supervisor.run)
        for route_name, agent in self._workers.items():
            builder.add_node(route_name, agent.run)
            # Sau mỗi worker, luôn quay lại supervisor để nó quyết định bước kế tiếp
            builder.add_edge(route_name, _SUPERVISOR)

        builder.set_entry_point(_SUPERVISOR)
        builder.add_conditional_edges(
            _SUPERVISOR,
            lambda state: state.route_history[-1] if state.route_history else DONE,
            {NEXT_RESEARCHER: NEXT_RESEARCHER, NEXT_ANALYST: NEXT_ANALYST,
             NEXT_WRITER: NEXT_WRITER, DONE: END},
        )
        return builder.compile()

    def run(self, state: ResearchState) -> ResearchState:
        result: Any = self._graph.invoke(state)
        # LangGraph 1.x trả về dict thuần dù state_schema là Pydantic model
        # (verify thật trên langgraph==1.2.11) — chuẩn hoá lại về ResearchState.
        if isinstance(result, ResearchState):
            return result
        return ResearchState.model_validate(result)
```

**Vì sao mỗi worker luôn có `add_edge(name, "supervisor")` (không đi thẳng worker → worker)?** Đây chính là hiện thực hoá kiến trúc router: Supervisor là **điểm quyết định duy nhất**, các worker không được tự ý gọi lẫn nhau — giữ đúng nguyên tắc "role clarity" (rubric) và tránh tạo ra luồng điều khiển ẩn khó trace.

**Vì sao constructor nhận `supervisor`/`researcher`/`analyst`/`writer` optional thay vì tự khởi tạo cứng?** Đây là *constructor injection* — production code không truyền gì (`MultiAgentWorkflow()`), dùng đúng agent thật; test truyền vào agent đã wire sẵn `SearchClient`/`LLMClient` giả để chạy toàn bộ graph (bao gồm cả routing logic thật) mà không tốn API call — đây là cách duy nhất để test *routing qua LangGraph* mà không phải mock chính LangGraph.

**Xác nhận quan trọng phát hiện khi test thật (đáng biết trước khi copy code):** `graph.invoke(state)` trên `langgraph==1.2.11` trả về **`dict` thuần**, không phải instance `ResearchState`, dù `state_schema=ResearchState` là một Pydantic model — verify bằng cách in `type(result)` ra `<class 'dict'>`. Đây không phải bug, đó là cách LangGraph nội bộ "làm phẳng" state qua các node. Nếu bỏ qua bước `model_validate(result)` ở cuối `run()`, mọi thứ gọi `MultiAgentWorkflow.run()` (`cli.py`, benchmark, test) sẽ nhận về `dict` thay vì `ResearchState` và crash ở `AttributeError` khi truy cập `.final_answer`. Đã verify `ResearchState.model_validate(result)` khôi phục đúng cả nested object (`SourceDocument` lồng trong `sources`).

**Chạy thật end-to-end lần đầu tiên** (`python -m multi_agent_research_lab.cli multi-agent --query "..."`) cho kết quả:

```
route_history: ["researcher", "analyst", "writer", "done"]
trace: 7 sự kiện (supervisor.route × 4, researcher.done, analyst.done, writer.done)
final_answer: có trích dẫn [1]..[5] đúng format
errors: []
```

Đây là lần đầu tiên lệnh `multi-agent` trong `README.md` chạy được thật thay vì raise `StudentTodoError` — đánh dấu hoàn thành "khung xương sống" của cả bài lab; các bước còn lại (Bước 6-9) là quan sát/đo lường/dọn dẹp trên nền đã chạy được này, không còn thay đổi kiến trúc lõi.

**Lưu ý về version LangGraph:** repo cài `langgraph==1.2.11` (một bản major khác hẳn API `langgraph==0.2.x` mà nhiều tài liệu/tutorial cũ mô tả) — `StateGraph`, `add_conditional_edges`, `set_entry_point`, `compile()` vẫn hoạt động tương thích ngược ở mức cơ bản dùng trong bài lab này, nhưng nếu học viên copy code mẫu từ một tutorial cũ hơn, nên đối chiếu bằng cách tự introspect (`inspect.signature(...)`) trên đúng version cài trong `.venv` thay vì tin tưởng tuyệt đối tài liệu — đây chính xác là cách bug "dict vs ResearchState" ở trên được phát hiện.

---

## 11. Bước 6 — Observability: logging & tracing

**File:** `observability/tracing.py` (mở rộng), tất cả `agents/*.run()` (tích hợp)

### Tại sao

Rubric có hẳn tiêu chí "Trace explanation": *"Nhóm giải thích được trace: ai làm gì, tốn bao nhiêu, sai ở đâu không?"* — `state.trace` (list of `{"name": ..., "payload": ...}`) đã được các agent ghi vào qua `add_trace_event()`, nhưng đó là log **nội dung nghiệp vụ**; `trace_span()` trong `observability/tracing.py` bổ sung khía cạnh **thời gian/hiệu năng** (duration mỗi bước) mà `add_trace_event` không tự động có.

### Cách làm (implementation thật, gồm 3 phần)

**1. Timing per-node, tập trung tại `graph/workflow.py`, không rải vào từng agent.** Thay vì sửa cả 4 file `agents/*.py` để mỗi agent tự bọc `trace_span` quanh chính nó (lặp code, và làm agent phải biết về observability — vi phạm tách lớp), tôi viết một wrapper duy nhất trong `graph/workflow.py`, áp dụng cho mọi node khi đăng ký vào graph:

```python
# graph/workflow.py
def _add_timed_node(builder: StateGraph[ResearchState, Any, Any, Any], name: str, agent: BaseAgent) -> None:
    def node(state: ResearchState) -> ResearchState:
        with trace_span(f"node.{name}") as span:
            state = agent.run(state)
        state.add_trace_event(f"node.{name}.timing", {"duration_seconds": span["duration_seconds"]})
        return state
    builder.add_node(name, node)  # đăng ký node ngay trong scope định nghĩa closure — xem lưu ý mypy bên dưới
```

`MultiAgentWorkflow.run()` bọc thêm một span tổng cho toàn bộ lần chạy, ghi `workflow.done` sau khi đã chuẩn hoá kết quả về `ResearchState`.

**Lưu ý mypy quan trọng (bug thật gặp khi build):** ban đầu tôi viết `_timed_node(name, agent) -> Callable[[ResearchState], ResearchState]` rồi `builder.add_node(name, _timed_node(...))` — code này **chạy đúng lúc runtime** nhưng `mypy --strict` báo lỗi "No overload variant of add_node matches" vì `StateGraph.add_node` có rất nhiều overload generic theo `NodeInputT`, và khi callable được truyền vào là *giá trị trả về của một hàm khác* (kiểu `Callable[[X], Y]` tường minh) thay vì một `def` cụ thể ngay tại chỗ gọi, mypy không suy luận được `NodeInputT` và fallback về `Never`, khiến overload nào cũng không khớp. Verify bằng một file repro tối giản (`StateGraph.add_node` với closure trả về từ helper vs. closure định nghĩa/gọi ngay tại chỗ) xác nhận: **định nghĩa closure và gọi `add_node` trong cùng một scope hàm** (như `_add_timed_node` ở trên — không return callable ra ngoài) thì mypy pass sạch. Đây là một giới hạn cụ thể của cách mypy suy luận generic qua overload phức tạp, không phải lỗi logic.

**2. Bật LangSmith thật qua `configure_tracing()`** (không cần sửa `agents/`, vì mỗi node LangGraph vốn là một LangChain Runnable, tự đọc biến môi trường `LANGCHAIN_*` khi thực thi):

```python
# observability/tracing.py
def configure_tracing(settings: Settings) -> bool:
    if not settings.langsmith_api_key:
        return False
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
    return True
```

Gọi trong `cli.py::_init()` (song song `configure_logging`), nên mọi lệnh CLI đều tự bật tracing nếu `.env` có `LANGSMITH_API_KEY`.

**3. Export trace ra file** (dùng lại `LocalArtifactStore` có sẵn) — thêm vào `cli.py::multi_agent()` sau khi có `result`:

```python
trace_path = LocalArtifactStore().write_text(
    "trace_latest.json", json.dumps(result.trace, indent=2)
)
```

### Đã verify thật cả 2 đường: local JSON trace và LangSmith thật

Chạy `python -m multi_agent_research_lab.cli multi-agent --query "..."` với `LANGSMITH_API_KEY` thật trong `.env` cho ra:

- `reports/trace_latest.json` chứa đúng 15 sự kiện: 4× `supervisor.route` + 4× `node.supervisor.timing` xen kẽ với `researcher.done`/`node.researcher.timing`, `analyst.done`/`node.analyst.timing`, `writer.done`/`node.writer.timing`, kết thúc bằng `workflow.done` (tổng 11.68s cho lần chạy này).
- Console in `"LangSmith tracing enabled (project=multi-agent-research-lab)"`.
- **Verify độc lập qua chính LangSmith API** (không chỉ tin console log): gọi `langsmith.Client().list_runs(project_name=...)` và thấy thật 3 run mới nhất với `status: success`, tên khớp node (`supervisor`, `_route_after_supervisor`) — xác nhận trace **thực sự được LangSmith nhận**, không phải chỉ set biến môi trường suông rồi không ai đọc.

**Bug rò rỉ env var phát hiện khi viết test** cho `configure_tracing`: vì hàm này set `os.environ[...]` **trực tiếp** (không qua `monkeypatch`), nếu test chỉ gọi `monkeypatch.delenv(name, raising=False)` trước khi test (để dọn trạng thái ban đầu) thì `monkeypatch` **không hề đăng ký teardown** cho biến đó — vì tại thời điểm gọi `delenv`, biến chưa tồn tại nên monkeypatch coi như "không có gì để undo". Hệ quả: sau khi `configure_tracing()` chạy xong bên trong test và set `LANGCHAIN_API_KEY=test-key`, biến này **rò rỉ sang mọi test chạy sau đó trong cùng phiên pytest** — và vì `test_worker_agents.py`/`test_workflow.py` build LangGraph thật, chúng vô tình cố gửi trace thật lên LangSmith bằng key giả, gây lỗi `403 Forbidden` lọt ra console dù tất cả test vẫn "PASS" (lỗi này không làm fail assertion nào, chỉ in ra stderr — dễ bị bỏ qua). Sửa bằng cách tự lưu/khôi phục `os.environ` thủ công trong `try/finally`, không dựa vào `monkeypatch` cho biến mà chính code-under-test ghi trực tiếp. **Bài học chung: `monkeypatch.delenv/setenv` chỉ đảm bảo dọn dẹp cho những gì monkeypatch tự thay đổi — nếu code-dưới-test tự ghi thẳng vào `os.environ`, phải tự chịu trách nhiệm dọn, đừng tin tưởng ngầm định.**

---

## 12. Bước 7 — Benchmark & report

**File:** `evaluation/benchmark.py`, `evaluation/report.py`

### Tại sao mở rộng thay vì dùng nguyên bản

`run_benchmark()` hiện tại **chỉ đo latency** — đúng ý đồ của người ra đề (cho một khung tối giản chạy được ngay, TODO ghi rõ: *"Add quality scoring, estimated token cost, citation coverage, and error rate"*). Không có 4 chỉ số này, `reports/benchmark_report.md` sẽ không thể trả lời câu hỏi cốt lõi của lab: **multi-agent có đáng chi phí thêm không?** — đúng insight từ corpus offline (`table TBL-01-1`): multi-agent có thể tăng quality 71→81 nhưng tốn gấp ~2 lần token so với baseline; nếu không đo cost, học viên sẽ không thấy được đánh đổi này.

### Cách làm (implementation thật)

```python
# evaluation/benchmark.py
import re
from multi_agent_research_lab.core.schemas import BenchmarkMetrics, ResearchQuery
from multi_agent_research_lab.core.state import ResearchState

_CITATION_RE = re.compile(r"\[(\d+)\]")

def run_benchmark(run_name: str, query: str, runner: Runner) -> tuple[ResearchState, BenchmarkMetrics]:
    started = perf_counter()
    try:
        state = runner(query)
        failed = bool(state.errors)
    except Exception as exc:  # noqa: BLE001 — benchmark phải sống sót qua lỗi 1 run
        safe_query = query if len(query) >= 5 else query.ljust(5, ".")
        state = ResearchState(request=ResearchQuery(query=safe_query))
        state.errors.append(f"benchmark: runner raised {type(exc).__name__}: {exc}")
        failed = True
    latency = perf_counter() - started

    metrics = BenchmarkMetrics(
        run_name=run_name,
        latency_seconds=latency,
        estimated_cost_usd=_total_cost_usd(state),
        citation_coverage=_citation_coverage(state),
        failure_rate=1.0 if failed else 0.0,
        notes=f"iterations={state.iteration}, errors={len(state.errors)}",
    )
    return state, metrics

def _total_cost_usd(state: ResearchState) -> float | None:
    known = [r.metadata["cost_usd"] for r in state.agent_results if r.metadata.get("cost_usd") is not None]
    return sum(known) if known else None

def _citation_coverage(state: ResearchState) -> float | None:
    if not state.sources or not state.final_answer:
        return None
    cited = {int(m) for m in _CITATION_RE.findall(state.final_answer)}
    hits = sum(1 for i in range(1, len(state.sources) + 1) if i in cited)
    return hits / len(state.sources)
```

**Vì sao `quality_score` không được tính tự động ở đây?** Vì rubric quy định rõ: *"Quality | rubric 0-10 do peer review"* — nghĩa là **con người chấm**, không phải máy tự chấm (tránh việc hệ thống tự cho điểm chính mình một cách thiên vị). Cách đúng: sau khi chạy benchmark, điền `metrics.quality_score` thủ công từ kết quả peer review (`docs/peer_review_rubric.md`), hoặc — nếu muốn tự động hoá — dùng chính `CriticAgent`/một LLM-judge độc lập với model đã sinh câu trả lời, rồi ghi rõ trong `notes` rằng điểm là "LLM-judge, không phải người chấm" để không đánh lừa người đọc report.

**Bug thật phát hiện khi viết test cho fallback path:** đoạn `except Exception` tồn tại để một query lỗi không làm sập cả loạt benchmark — nhưng bản đầu tôi viết `ResearchState(request=ResearchQuery(query=query))` dùng lại đúng `query` gốc. Nếu chính `query` đó có `len < 5` (giới hạn `min_length=5` của `ResearchQuery`), dòng fallback này **tự nó cũng raise `ValidationError`**, thoát thẳng ra khỏi `run_benchmark` — nghĩa là except-block được viết ra để "cứu" chương trình lại chính là nguyên nhân làm nó sập, chỉ trong một tình huống hẹp hơn (query ngắn) nhưng vẫn là sập. Phát hiện bằng cách viết test cố tình dùng `runner` raise lỗi + query rất ngắn (`"hi"`) — không phải suy luận trên giấy. Sửa bằng cách pad query lên đủ 5 ký tự (`query.ljust(5, ".")`) chỉ trong nhánh fallback, không đụng tới hành vi query hợp lệ. **Bài học: một khối `except` phải tự nó exception-safe — nếu code bên trong `except` có thể raise vì cùng loại input đã gây ra lỗi ban đầu, nó không phải là một fallback thật sự.**

**Chạy benchmark thật với danh sách query trong `configs/lab_default.yaml`** — thêm lệnh CLI mới `benchmark` (tái dùng `_run_single_agent`/`_run_multi_agent` đã tách ra từ `baseline`/`multi-agent` để tránh trùng code), đọc `benchmark.queries` bằng `yaml.safe_load` (gap ẩn từng nêu ở §3 nay đã được lấp), chạy qua `run_benchmark`, rồi ghi `reports/benchmark_report.md` bằng `render_markdown_report` + `LocalArtifactStore`.

### Kết quả chạy thật (`python -m multi_agent_research_lab.cli benchmark`, cả 3 query × 2 chế độ, API thật)

```
6 run(s), 0 failed. Average latency: 10.89s. Total estimated cost: $0.0027.

| Run                                              | Latency | Cost   | Citation cov. |
|---------------------------------------------------|--------:|-------:|---------------:|
| single_agent::Research GraphRAG state-of-the-art   | 13.15s  | 0.0004 |               |
| multi_agent::Research GraphRAG state-of-the-art    | 18.26s  | 0.0008 |          100% |
| single_agent::Compare single-agent and multi-agent | 2.84s   | 0.0001 |               |
| multi_agent::Compare single-agent and multi-agent  | 15.71s  | 0.0007 |           60% |
| single_agent::Summarize production guardrails      | 5.07s   | 0.0002 |               |
| multi_agent::Summarize production guardrails       | 10.30s  | 0.0005 |          100% |
```

Đây chính là bằng chứng định lượng cho luận điểm cốt lõi của bài lab (và của working thesis trong corpus offline topic 1): multi-agent **luôn chậm hơn và tốn hơn ~2× chi phí** so với single-agent baseline (đúng chiều với table `TBL-01-1` của corpus), nhưng đổi lại có `citation_coverage` 60-100% — một thuộc tính **single-agent baseline không thể có được về mặt cấu trúc**, vì nó không có bước Researcher nên `state.sources` luôn rỗng → `citation_coverage` luôn `None` (ô trống trong bảng, không phải `0%` — một điểm tinh tế: "không đo được" khác với "đo được là 0"). Đây chính xác là dữ liệu cần trích vào `docs/design_template.md` mục "Why multi-agent?" và exit ticket.

---

## 13. Bước 8 — Cập nhật bộ test

> **Cập nhật:** phần `SupervisorAgent` bên dưới đã được xử lý ngay tại Bước 3 (§8), không đợi tới đây — xem `tests/test_supervisor.py`. Lý do và cách làm giữ nguyên như mô tả dưới đây, áp dụng tương tự cho Researcher/Analyst/Writer khi tới lượt các agent đó.

### Tại sao `test_agents_todo.py` được thiết kế để tự FAIL

Đọc kỹ docstring của file:

> *"Test này chỉ xác nhận skeleton còn nguyên TODO. Sau khi bạn implement SupervisorAgent, test này SẼ FAIL - đó là điều bình thường."*

Đây là một **"canary test"** có chủ đích: nó tồn tại để đảm bảo `make test` fail rõ ràng nếu ai đó copy code có sẵn mà quên implement, và **cố ý biến mất** khi lab hoàn thành đúng. Nếu học viên implement `SupervisorAgent` xong mà không xoá/thay test này, CI (`.github/workflows/ci.yml`) sẽ báo đỏ — đây là tín hiệu (không phải bug) rằng cần bước dọn dẹp cuối.

### Thay thế bằng test thật cho routing policy

```python
# tests/test_agents_todo.py → đổi tên/nội dung, ví dụ tests/test_supervisor.py
from multi_agent_research_lab.agents.supervisor import SupervisorAgent, NEXT_RESEARCHER, DONE
from multi_agent_research_lab.core.schemas import ResearchQuery, SourceDocument
from multi_agent_research_lab.core.state import ResearchState


def _state(**kw) -> ResearchState:
    return ResearchState(request=ResearchQuery(query="Explain multi-agent systems"), **kw)


def test_routes_to_researcher_when_no_sources() -> None:
    state = SupervisorAgent().run(_state())
    assert state.route_history[-1] == NEXT_RESEARCHER


def test_stops_at_max_iterations() -> None:
    state = _state(iteration=6)  # bằng Settings.max_iterations mặc định
    state = SupervisorAgent().run(state)
    assert state.route_history[-1] == DONE
```

Nên bổ sung thêm test cho `ResearcherAgent`/`AnalystAgent`/`WriterAgent` dùng `LLMClient`/`SearchClient` giả (fake/mocked), và một test end-to-end cho `MultiAgentWorkflow.run()` xác nhận `route_history` kết thúc bằng `"done"` và `final_answer` không rỗng — tương tự cách `tests/test_state.py` và `tests/test_report.py` đã kiểm chứng phần code có sẵn (giữ style test đó làm chuẩn).

### Cách thực tế đã làm: viết test song song với từng bước, rồi dùng coverage để tìm chỗ còn thiếu

Trên thực tế, thay vì dồn hết việc viết test vào một bước riêng ở cuối, mỗi bước trước đó (3-7) đều đã có test đi kèm ngay khi code được viết (`test_supervisor.py`, `test_worker_agents.py`, `test_workflow.py`, `test_tracing.py`, `test_benchmark.py`/`test_report.py`) — 36 test tính tới hết Bước 7. Tới Bước 8, việc còn lại không phải "viết test từ đầu" mà là **đo coverage để tìm khoảng trống thật** thay vì đoán:

```bash
pytest --cov=multi_agent_research_lab --cov-report=term-missing -q
```

Kết quả (trước khi bổ sung): **72%** tổng thể, với 4 file ở **0%** (`cli.py`, `observability/logging.py`, `services/storage.py`, `utils/timer.py`) và `services/search_client.py` chỉ **44%** — dù đây là logic thật (tokenize, scoring, cache, load corpus) đã được tôi verify bằng script thủ công ở Bước 2, nhưng **chưa từng có test tự động** cho nó; các test agent khác chỉ dùng `_FakeSearchClient`, không bao giờ chạm vào `SearchClient` thật.

Bổ sung 4 file test mới (`test_search_client.py`, `test_llm_client.py`, `test_storage.py`, `test_timer.py`, `test_logging.py`) đưa coverage lên **84%** tổng thể, và **100%** cho mọi module trừ `cli.py` (phần Typer CLI — đã được verify bằng chạy tay thật xuyên suốt các bước trước, không viết unit test riêng vì cần mock quá nhiều dependency để giá trị thu về không tương xứng công sức).

**2 bug thật phát hiện nhờ viết test cho các file "phụ" tưởng như không có gì để test:**

1. **`observability/logging.py::configure_logging` — bug re-configuration silent no-op.** `logging.basicConfig()` (không có `force=True`) chỉ thật sự có tác dụng ở **lần gọi đầu tiên** trong một process; mọi lần gọi sau đó là no-op im lặng nếu root logger đã có handler. Verify bằng script tay: gọi `configure_logging("WARNING")` rồi `configure_logging("DEBUG")` — level vẫn giữ nguyên 30 (WARNING) thay vì đổi thành 10 (DEBUG). Bug này gần như vô hại trong CLI (mỗi lệnh là 1 process mới, chỉ gọi 1 lần) nhưng ảnh hưởng thật tới đúng đối tượng học viên: **notebook** — nếu chạy lại cell `configure_logging(...)` với level khác giữa các lần thử, log level sẽ không đổi, gây khó hiểu khi debug. Sửa bằng thêm `force=True`.
2. **`utils/timer.py::elapsed_timer` vs `observability/tracing.py::trace_span` — hai tiện ích đo thời gian có ngữ nghĩa khác nhau, không ai ghi lại điều này.** `trace_span` "đóng băng" `duration_seconds` khi thoát khối `with` (dùng `finally`). `elapsed_timer` thì **không bao giờ đóng băng** — hàm `elapsed()` trả về vẫn tiếp tục tính thời gian tăng dần kể cả sau khi khối `with` đã kết thúc, vì nó chỉ là closure tính `perf_counter() - started` mỗi lần gọi, không có bước "chốt" giá trị. Đây không phải bug (cả hai hành vi đều có lý do tồn tại), nhưng là một **bất đối xứng ngầm** giữa 2 tiện ích trông giống hệt nhau về API — nếu học viên dùng nhầm `elapsed_timer` ở nơi cần giá trị "đóng băng" (ví dụ ghi log sau khi `with` đã thoát), số liệu sẽ sai lệch theo thời gian trôi qua giữa lúc thoát `with` và lúc thực sự đọc giá trị. Viết test `test_elapsed_timer_keeps_advancing_after_the_with_block` để ghi lại hành vi này tường minh, tránh ai đó "sửa" nó thành giống `trace_span` mà không biết đang đổi hành vi.

**Bài học tổng quát cho Bước 8:** "chưa có test" và "không cần test" là hai việc khác nhau — coverage report chỉ mất vài giây để chạy nhưng chỉ thẳng ra chính xác cái gì đang là góc khuất, thay vì phải nhớ hoặc đoán. Hai bug ở trên đều nằm trong những file tưởng như "quá đơn giản để cần test" (`configure_logging` 4 dòng, `elapsed_timer` 8 dòng) — minh chứng rằng độ đơn giản của code không tỷ lệ thuận với việc nó có đúng behavior mong đợi hay không, đặc biệt với global state (root logger) hay bán-định nghĩa hành vi cạnh biên (không đóng băng vs đóng băng).

---

## 14. Bước 9 — Lint, type-check, CI, pre-commit

```bash
ruff check src tests           # make lint
ruff format --check src tests  # make format --check
mypy src                       # make typecheck (strict = true)
pytest                         # make test
bash scripts/check_todos.sh    # xác nhận hết TODO(student)
pre-commit run --all-files     # ruff + ruff-format qua git hook
```

(Trên Windows không có sẵn `make` — xem bảng thay thế ở §5. Toàn bộ 4 lệnh trên đã chạy sạch xuyên suốt các bước trước; phần còn lại của bước này là ráp chúng lại thành một lượt xác nhận cuối cùng và kiểm tra chính CI/pre-commit — 2 thứ chưa từng được tự thực thi cho tới giờ.)

**Vì sao `mypy strict = true`?** (`pyproject.toml`) — bắt buộc mọi hàm mới đều có type hint đầy đủ, kể cả return type; đây là lý do mọi hàm viết ở các bước trước đều ghi rõ `-> ResearchState`, `-> LLMResponse`, v.v. Thiếu type hint sẽ khiến `mypy` fail dù logic đúng.

**Lưu ý về `scripts/check_todos.sh`:** script grep cả `src`, `tests`, **và `docs`** — chạy thật cho kết quả đúng như dự đoán: **0 marker thật trong `src`/`tests`**, chỉ còn nhiễu từ `docs/design_template.md` (5 TODO thật, chưa điền — việc của Bước 10), `docs/lab_guide.md` (3 chỗ là văn bản mô tả milestone, không phải marker cần xoá), và chính `docs/solution_walkthrough.md` (tài liệu này trích dẫn cụm từ "TODO(student)" nhiều lần để giải thích, cũng bị đếm nhầm — nhiễu vô hại). Script dùng `|| true` nên luôn exit 0 — nó là công cụ **đọc bằng mắt**, không phải gate tự động chặn CI.

### Bug thật phát hiện: CI sẽ đỏ hoàn toàn nếu không sửa

`ci.yml` (bước cài dependency) ghi `pip install -e ".[dev]"` — **thiếu nhóm `llm`** (openai, langgraph, langchain-core, langsmith). Điều này **đúng và vô hại với skeleton gốc** (mọi agent/service chỉ raise `StudentTodoError`, không import SDK nào), nhưng sau khi implement xong, `services/llm_client.py` import `openai` và `graph/workflow.py` import `langgraph` ở top-level — nghĩa là **mọi test file nào import tới các agent/graph này đều sẽ fail ngay ở bước collect**, trước khi chạy được dòng test nào.

**Verify bằng cách dựng đúng một venv y hệt CI** (chỉ cài `.[dev]`, không cài `.[dev,llm]`) rồi chạy `pytest` — kết quả thật:

```
ModuleNotFoundError: No module named 'openai'
ERROR tests/test_llm_client.py
ERROR tests/test_supervisor.py
ERROR tests/test_worker_agents.py
ERROR tests/test_workflow.py
4 errors during collection
```

4 file test sập ngay từ bước import, `ruff check`/`ruff format --check` vẫn pass bình thường (chúng không cần import code) — nghĩa là nếu chỉ tin vào lint xanh mà không tự chạy `pytest` trong đúng môi trường CI, sẽ không phát hiện ra vấn đề này. Đối chiếu lại thì `Makefile::install` **đã đúng từ đầu** (`pip install -e ".[dev,llm]"`) — chỉ riêng `ci.yml` là nơi duy nhất còn sót cấu hình cũ của skeleton, một inconsistency giữa 2 nơi định nghĩa "cách cài đặt dependency" mà không ai đối chiếu chéo.

**Sửa:** đổi `ci.yml` thành `pip install -e ".[dev,llm]"`, verify lại bằng đúng quy trình trên (venv sạch cài `.[dev,llm]`) — cả 3 bước CI (lint, format check, pytest) pass sạch, 55/55 test.

**Bài học: một pipeline CI/cấu hình cài đặt chỉ có thể coi là "đúng" nếu được chạy thử trong đúng môi trường nó mô tả — đọc file YAML bằng mắt không phát hiện ra được rằng một extras-group bị thiếu, vì thiếu sót đó không gây lỗi cú pháp gì, chỉ gây lỗi runtime khi thực thi.**

### Bug thứ hai: `.gitignore` đang loại bỏ chính deliverable bắt buộc

`.gitignore` gốc có `reports/*.json` **và** `reports/*.md`. README mục Deliverables lại yêu cầu nộp chính xác `reports/benchmark_report.md`, và `CONTRIBUTING.md` nhắc lại: *"Viết benchmark report trong `reports/benchmark_report.md`."* Verify bằng `git status --short --ignored reports/` sau khi đã sinh cả 2 file thật ở Bước 7: cả `benchmark_report.md` **và** `trace_latest.json` đều hiện `!!` (bị ignore hoàn toàn) — nghĩa là nếu học viên làm đúng mọi hướng dẫn (chạy `cli benchmark`, rồi `git add`/commit/push PR), file report **âm thầm biến mất khỏi bài nộp**, không có cảnh báo nào từ git (không giống lỗi CI ở trên — lỗi này thậm chí không hiện ra khi debug local, vì mọi thứ "trông" vẫn ổn).

**Sửa:** bỏ `reports/*.md` khỏi `.gitignore`, giữ nguyên `reports/*.json` (trace là artifact sinh lại mỗi lần chạy CLI, chứa timestamp/duration đổi liên tục — không có giá trị diff, hợp lý để ignore) và thêm `.coverage` (artifact của `pytest-cov`, phát sinh khi chạy coverage ở Bước 8, cũng chưa từng được ignore). Verify lại: `benchmark_report.md` giờ hiện `??` (untracked, sẵn sàng `git add`), `trace_latest.json`/`.coverage` vẫn `!!` đúng ý đồ.

**Bài học: `.gitignore` viết theo pattern rộng (`reports/*.md`) rất dễ vô tình nuốt luôn một file cụ thể mà assignment yêu cầu nộp — luôn đối chiếu chéo `.gitignore` với danh sách deliverable trong README, đừng chỉ tin rằng "ignore file tạm" là an toàn mặc định.**

### Một điểm đáng cân nhắc, chưa tự ý sửa

CI hiện **không chạy `mypy`** — chỉ có `ruff check`, `ruff format --check`, `pytest`. `Makefile`/`CONTRIBUTING.md` đều nhắc `make typecheck` như một bước bắt buộc trước khi nộp bài, nhưng CI không enforce nó. Đây có thể là chủ đích của người ra đề (mypy strict đôi khi khắt khe với một lab 2 giờ, không muốn CI đỏ vì lỗi type nhỏ) hoặc là một thiếu sót — không đủ căn cứ để khẳng định, nên tôi **không tự ý thêm** bước mypy vào `ci.yml`. Nếu muốn CI chặt hơn, thêm một step `- name: Type check` + `run: mypy src` vào `ci.yml` là đủ (đã verify mypy chạy sạch, an toàn để bật).

---

## 15. Bước 10 — Hoàn thiện tài liệu & deliverables

### `docs/design_template.md` — đã điền đầy đủ

File template rỗng ban đầu (mọi mục đều là `TODO(student)`) đã được điền lại **bằng chính số liệu và quyết định thật** thu thập xuyên suốt Bước 1-9 — không phải nội dung giả định. Điểm khác so với gợi ý ban đầu ở đây: thay vì chỉ mô tả định tính "Model bịa nguồn → cần Critic/citation audit", bản điền thật trích thẳng số liệu benchmark thật (latency ~2.1×, cost ~2.9×, citation coverage 60-100% cho multi-agent vs. `None` có cấu trúc cho single-agent) và một sự kiện Critic thật đã bắt được lỗi trích dẫn — biến mục "Why multi-agent?" từ một đoạn lý thuyết thành một kết luận có bằng chứng đo được, đúng tinh thần rubric *"Benchmark | Có so sánh single vs multi-agent bằng metric cụ thể không?"*.

### `reports/benchmark_report.md` — đã sinh và **đã sửa 1 bug khiến nó suýt biến mất khỏi bài nộp**

Sinh tự động bằng `render_markdown_report()` (Bước 7), nhưng phát hiện ở Bước 9: `.gitignore` gốc có `reports/*.md`, loại bỏ hoàn toàn file này khỏi git — đã sửa (xem §14). Nếu không kiểm tra bằng `git status --ignored`, deliverable bắt buộc này sẽ âm thầm không có mặt trong bài nộp dù file tồn tại đúng trên đĩa.

### Đoạn giải thích failure mode — `docs/failure_mode_analysis.md`

Thay vì để lỏng trong tài liệu này, đã tách thành file riêng (khớp cách README liệt kê nó như một deliverable độc lập, ngang hàng với `reports/benchmark_report.md`). Cấu trúc thật đã dùng:

```text
Failure mode gặp phải: Writer bỏ sót trích dẫn cho nguồn đã cung cấp
Triệu chứng quan sát được: CriticAgent (chạy độc lập) phát hiện "Source [3] is listed but never cited"
Nguyên nhân gốc: Prompt yêu cầu trích dẫn chỉ là soft constraint, không có bước tự kiểm tra coverage
Cách fix: (1) CriticAgent độc lập — đã implement, đã bắt lỗi thật; (2) hướng rẻ hơn chưa làm —
          route lại writer khi _citation_coverage() dưới ngưỡng, thay vì chấp nhận output luôn
Residual risk: LLM-judge (Critic) vẫn có thể bỏ sót — cần kiểm tra tất định (regex) làm lưới cuối
```

File này **không dùng** trực tiếp 6 failure mode chuẩn của corpus (`coordination overhead`, `duplicated research`, ...) làm khung — vì đó là failure mode ở tầng *kiến trúc/điều phối multi-agent*, còn lỗi thật quan sát được ở đây là failure mode ở tầng *hành vi một agent đơn lẻ không tự kiểm chứng output của chính nó* (gần với `K008`/`K024` trong `fact_bank` hơn là `failure_mode_library`). Ngoài ra file còn liệt kê tóm tắt 8 bug engineering/tooling khác phát hiện trong toàn bộ quá trình (đầy đủ trong các mục §7, §11-14 của tài liệu này).

---

## 16. Peer review & Exit ticket

`docs/peer_review_rubric.md` chấm 5 tiêu chí × 0-2 điểm (Role clarity, State design, Failure guard, Benchmark, Trace explanation) — mỗi tiêu chí map thẳng tới một bước đã làm ở trên (bước 9↔Role clarity, bước 8+ResearchState↔State design, bước 8's guard↔Failure guard, bước 12↔Benchmark, bước 11↔Trace explanation). Nếu một tiêu chí bị điểm thấp khi peer review, quay lại đúng bước tương ứng trong tài liệu này để sửa.

**Exit ticket** (2 câu, trả lời dựa trên chính benchmark đã đo, không chỉ lý thuyết):

1. *Case nào nên dùng multi-agent?* — Case có nhu cầu thông tin/kiểm chứng thực sự khác biệt giữa các bước (cần tìm nguồn riêng, phân tích riêng, viết riêng) — khớp working thesis của corpus và nên trích số liệu benchmark thật (ví dụ: `citation_coverage` cao hơn X%).
2. *Case nào không nên?* — Câu hỏi ngắn, một nguồn thông tin duy nhất, không cần kiểm chứng chéo — baseline single-agent thắng về latency/cost mà chất lượng không thua kém đáng kể (đối chiếu case study `CASE-01-B` trong corpus: *"A six-agent pipeline repeats the same source extracts and spends most of its time on handoffs and synthesis"*).

---

## 17. Bảng tổng hợp toàn bộ `TODO(student)` — tại sao & thay đổi ra sao

| # | Vị trí | Tại sao là quyết định của học viên (không thể "để sẵn") | Thay đổi ra sao (tóm tắt) |
|---|---|---|---|
| 1 | `agents/supervisor.py::run` | Chính sách điều phối là trái tim kiến trúc, không có "đáp án đúng" duy nhất | State-machine dựa trên field thiếu trong `ResearchState` + guard `max_iterations` (§8) |
| 2 | `agents/researcher.py::run` | Nguồn dữ liệu (Tavily thật/offline corpus/mock) là lựa chọn tuỳ ngữ cảnh triển khai | Gọi `SearchClient`, guard nguồn rỗng, ghi `sources`+`research_notes` (§9.1) |
| 3 | `agents/analyst.py::run` | Cách "phân tích" là nghiệp vụ, phụ thuộc prompt engineering của từng người | Gọi `LLMClient` với prompt phân tích, guard `sources` rỗng (§9.2) |
| 4 | `agents/writer.py::run` | Văn phong, cấu trúc trích dẫn tuỳ thuộc audience | Gọi `LLMClient`, ép format `[n]`, fallback `research_notes` (§9.3) |
| 5 | `agents/critic.py::run` (bonus) | Có đáng thêm bước kiểm chứng hay không là đánh đổi cost/quality | Optional: LLM-judge độc lập kiểm tra claim vs sources (§9.4) |
| 6 | `graph/workflow.py::build/run` | Chọn framework orchestration (LangGraph/while-loop) và cấu trúc node/edge | `StateGraph` với node=agent, Supervisor là hub điều hướng duy nhất (§10) |
| 7 | `services/llm_client.py::complete` | Chọn provider, chính sách retry/timeout/cost | OpenAI SDK + `tenacity` retry + tính `cost_usd` từ usage (§6) |
| 8 | `services/search_client.py::search` | Chọn nguồn search — web thật hay offline corpus | Đọc `ai_agent_offline_research_corpus_v2/`, keyword ranking (§7) |
| 9 | `evaluation/benchmark.py::run_benchmark` | Định nghĩa "chất lượng"/"chi phí" cụ thể là quyết định nghiệp vụ | Thêm `citation_coverage`, `estimated_cost_usd`, `failure_rate` (§12) |
| 10 | `evaluation/report.py::render_markdown_report` | Mức độ chi tiết report cần cho người đọc là ai (giảng viên, team) | Thêm phần phân tích/so sánh, không chỉ bảng thô (§12, mở rộng) |
| 11 | `observability/tracing.py::trace_span` | Chọn provider tracing (LangSmith/Langfuse/tự dựng) | Giữ span tối giản hoặc nối LangSmith qua env var (§11) |
| 12 | `docs/design_template.md` (toàn bộ) | Chỉ học viên biết lý do thiết kế thật của chính hệ thống mình xây | Điền dựa trên các quyết định đã đưa ra ở trên (§15) |

---

## 18. Chạy thử & xác nhận end-to-end

```bash
# Sau khi hoàn thành tất cả các bước trên:
make lint && make typecheck && make test
bash scripts/check_todos.sh          # phải không còn output nào trong src/

python -m multi_agent_research_lab.cli baseline \
  --query "Research GraphRAG state-of-the-art and write a 500-word summary"

python -m multi_agent_research_lab.cli multi-agent \
  --query "Research GraphRAG state-of-the-art and write a 500-word summary"

# Container hoá (tuỳ chọn, dùng Dockerfile có sẵn)
docker build -t multi-agent-research-lab .
docker run --env-file .env multi-agent-research-lab \
  multi-agent --query "Compare single-agent and multi-agent workflows for customer support"
```

**Checklist hoàn thành:**

- [ ] `make lint / typecheck / test` xanh
- [ ] `bash scripts/check_todos.sh` không còn TODO trong `src/`
- [ ] CLI `baseline` và `multi-agent` chạy được, in ra `final_answer` có trích dẫn
- [ ] `reports/benchmark_report.md` tồn tại, có cả 2 dòng `single_agent` và `multi_agent`
- [ ] Trace export (JSON hoặc LangSmith link) có thể trình bày được
- [ ] `docs/design_template.md` điền đầy đủ, không còn "TODO"
- [ ] Đoạn giải thích failure mode đã viết (§15)
- [ ] Sẵn sàng trả lời 2 câu exit ticket (§16)

---

## 19. Rủi ro & lỗi thường gặp

| Triệu chứng | Nguyên nhân thường gặp | Cách xử lý |
|---|---|---|
| `ssl.SSLCertVerificationError` khi gọi API trên macOS | Python từ python.org không dùng CA store của OS | Xem `docs/lab_guide.md` mục Troubleshooting — chạy `Install Certificates.command` hoặc set `SSL_CERT_FILE=$(python -m certifi)` |
| CLI treo mãi không dừng | Quên gọi `settings.max_iterations` trong `SupervisorAgent`, hoặc guard đặt sai thứ tự | Đảm bảo kiểm tra `state.iteration >= max_iterations` là điều kiện **đầu tiên** trong `_decide()` |
| `StudentTodoError` vẫn xuất hiện dù đã sửa | Sửa nhầm bản copy trong notebook thay vì file thật trong `src/` | Notebook không được import vào `src/` — logic phải được **chuyển tay** theo bảng mapping ở cuối notebook |
| `test_agents_todo.py` fail sau khi implement | Đúng như thiết kế — đây là canary test | Xoá/thay bằng test thật (§13), không phải bug cần fix ngược |
| `mypy strict` fail dù logic đúng | Thiếu type hint cho tham số/return | Thêm type hint đầy đủ, tránh `Any` không cần thiết |
| `citation_coverage` luôn = 0 dù Writer có trích nguồn | Định dạng trích dẫn trong prompt không khớp cách đếm trong `_citation_coverage` | Đồng bộ format `[n]` giữa prompt Writer (§9.3) và hàm đếm (§12) |
| Benchmark không tái lập được giữa các lần chạy | Dùng Tavily thật (kết quả tìm kiếm đổi theo thời gian) | Ưu tiên `SearchClient` đọc `ai_agent_offline_research_corpus_v2/` cho benchmark chính thức (§7) |
| `SearchClient.search()` trả kết quả không liên quan tới query nhưng vẫn điểm cao | Scoring theo substring (`text.count(term)`) khiến từ ngắn (`"in"`, `"is"`) khớp nhầm bên trong các từ dài không liên quan (`"coordination"`) | Tokenize theo từ nguyên vẹn bằng regex + loại stopword trước khi đếm (§7 mục "5 quyết định thiết kế") |
| `SearchClient` trả `match_score` sai/lẫn giữa các query liên tiếp | Mutate trực tiếp object `SourceDocument` đã cache thay vì tạo bản sao | Dùng `doc.model_copy(update=...)` thay vì gán field trên object lấy từ cache dùng chung (§7) |
