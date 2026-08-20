# Failure Mode Analysis

## Failure mode: Writer bỏ sót trích dẫn cho nguồn đã được cung cấp

### Triệu chứng quan sát được

Trong một lần chạy thật (`ResearcherAgent → AnalystAgent → WriterAgent → CriticAgent`, query: *"task decomposition and coordination overhead in multi-agent research systems"*), Writer nhận 5 nguồn từ Researcher nhưng `final_answer` chỉ trích dẫn `[1]` và `[2]`. `CriticAgent` — chạy độc lập, không thấy prompt gốc của Writer — phát hiện:

> "The claim about the study conducted over 8 weeks and 2,400 agent runs lacks specific citations, as the source does not detail the study's design or limitations in the final answer."
> "Source [3] is listed but never cited."

### Nguyên nhân gốc

`WriterAgent`'s system prompt yêu cầu trích dẫn (*"You MUST cite sources inline as [1], [2], ..."*) nhưng đây là **soft constraint** — LLM có thể tuân thủ một phần (trích 2/5 nguồn) mà output vẫn "trông hợp lệ" (có dấu `[n]`, đúng format, đọc mượt). Không có bước nào trong `WriterAgent.run()` tự kiểm tra xem toàn bộ nguồn được cung cấp có thực sự được dùng hay không — nó tin tưởng hoàn toàn vào việc model làm đúng theo prompt.

Đây chính là failure mode "thiếu independent verification" mà `fact_bank` của corpus offline cảnh báo (`K008`: *"A verifier is strongest when it uses an independent evidence path"*): một agent đơn lẻ không tự phát hiện được lỗi của chính mình, vì nó không có góc nhìn nào khác ngoài chính output nó vừa tạo ra.

### Cách fix

1. **Đã có (bonus, đã implement và verify thật):** `CriticAgent` — một lệnh gọi LLM độc lập, review `final_answer` so với `sources`, đã phát hiện đúng vấn đề trên trong một lần chạy thật. Đánh đổi: tốn thêm ~1 lệnh gọi LLM mỗi lần bật (cost + latency tăng thêm), nên để tuỳ chọn thay vì mặc định nằm trong route của Supervisor.
2. **Cách fix rẻ hơn, không cần thêm LLM call:** `evaluation/benchmark.py::_citation_coverage()` đã có sẵn hàm đếm tất định (regex `[n]` đối chiếu số lượng `sources`) — có thể tái dùng ngay sau `WriterAgent.run()`: nếu coverage dưới một ngưỡng (vd. 50%), Supervisor route quay lại `writer` kèm một ghi chú bổ sung ("còn thiếu trích dẫn cho nguồn X, Y") thay vì chấp nhận output luôn. Đây là hướng nâng cao **chưa implement** trong `SupervisorAgent` hiện tại — routing hiện tại đi thẳng `writer → done`, chưa có vòng lặp tự sửa lỗi.
3. **Residual risk:** kể cả bật Critic, review bằng một LLM khác vẫn có thể bỏ sót (đúng tinh thần "confidence score không thay thế được đánh giá chất lượng bằng chứng" — `fact K024` của corpus). Kiểm tra tất định (đếm `[n]` bằng regex) nên luôn là lưới an toàn cuối cùng, không chỉ dựa vào LLM-judge.

---

## Các failure mode khác (tầng engineering/tooling) phát hiện trong quá trình implement

Ngoài failure mode ở tầng hành vi agent trên, quá trình implement + viết test + verify thật (không chỉ đọc code) đã phát hiện một loạt bug ở tầng hạ tầng. Chi tiết đầy đủ (nguyên nhân, cách verify, cách fix) nằm trong `docs/solution_walkthrough.md`; tóm tắt:

| Bug | Nơi | Cách fix |
|---|---|---|
| Substring matching gây điểm liên quan giả (`"in"` khớp nhầm bên trong `"coordination"`) | `services/search_client.py` | Tokenize theo từ nguyên vẹn + loại stopword |
| Mutate object dùng chung trong cache, rò `match_score` giữa các lần `search()` | `services/search_client.py` | `doc.model_copy(update=...)` thay vì gán field trực tiếp |
| `mypy --strict` fail vì overload generic của LangGraph không suy luận được qua một hàm trung gian | `graph/workflow.py` | Định nghĩa closure và gọi `add_node` trong cùng scope hàm |
| Biến môi trường rò rỉ giữa các test vì `monkeypatch` không track được thứ code ghi trực tiếp vào `os.environ` | `tests/test_tracing.py` | Tự lưu/khôi phục `os.environ` bằng `try/finally` |
| Except-fallback trong benchmark tự nó có thể raise nếu query quá ngắn — làm hỏng chính cơ chế "không được sập" | `evaluation/benchmark.py` | Pad query đủ độ dài chỉ trong nhánh fallback |
| `configure_logging()` là no-op câm lặng từ lần gọi thứ 2 trở đi trong cùng process | `observability/logging.py` | Thêm `force=True` vào `logging.basicConfig()` |
| CI cài thiếu nhóm dependency `llm` — sẽ đỏ hoàn toàn ngay khi có code thật (không chỉ skeleton) | `.github/workflows/ci.yml` | Đổi `pip install -e ".[dev]"` → `".[dev,llm]"` |
| `.gitignore` loại bỏ chính deliverable bắt buộc (`reports/*.md` khớp cả `benchmark_report.md`) | `.gitignore` | Bỏ `reports/*.md`, giữ `reports/*.json` |

**Điểm chung của mọi bug trên:** không cái nào lộ ra khi chỉ đọc code bằng mắt hoặc chỉ chạy đúng 1 lần theo happy path. Tất cả chỉ lộ ra khi **chủ động thử kịch bản xấu** — query không liên quan, query rất ngắn, gọi lại một hàm 2 lần trong cùng process, dựng venv sạch giống hệt CI, chạy `git status --ignored` thay vì `git status` thường — thay vì tin rằng "chạy được một lần là xong việc".
