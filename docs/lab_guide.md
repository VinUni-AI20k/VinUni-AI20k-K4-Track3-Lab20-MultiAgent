# Lab Guide: Multi-Agent Research System

## Scenario

Bạn cần xây dựng một research assistant có thể nhận câu hỏi dài, tìm thông tin, phân tích và viết câu trả lời cuối cùng. Lab yêu cầu so sánh hai cách làm:

1. **Single-agent baseline**: một agent làm toàn bộ.
2. **Multi-agent workflow**: Supervisor điều phối Researcher, Analyst, Writer.

## Quy tắc quan trọng

- Không thêm agent nếu không có lý do rõ ràng.
- Mỗi agent phải có responsibility riêng.
- Shared state phải đủ rõ để debug.
- Phải có trace hoặc log cho từng bước.
- Phải benchmark, không chỉ nhìn output bằng cảm tính.

## Milestone 1: Baseline

File gợi ý:

- `src/multi_agent_research_lab/cli.py`
- `src/multi_agent_research_lab/services/llm_client.py`

TODO(student): thay baseline placeholder bằng một call LLM thật.

## Milestone 2: Supervisor

File gợi ý:

- `src/multi_agent_research_lab/agents/supervisor.py`
- `src/multi_agent_research_lab/graph/workflow.py`

TODO(student): implement routing policy.

Gợi ý câu hỏi thiết kế:

- Khi nào gọi Researcher?
- Khi nào gọi Analyst?
- Khi nào gọi Writer?
- Khi nào stop?
- Nếu agent fail thì retry hay fallback?

## Milestone 3: Worker agents

File gợi ý:

- `src/multi_agent_research_lab/agents/researcher.py`
- `src/multi_agent_research_lab/agents/analyst.py`
- `src/multi_agent_research_lab/agents/writer.py`

TODO(student): implement từng worker.

## Milestone 4: Trace và benchmark

File gợi ý:

- `src/multi_agent_research_lab/observability/tracing.py`
- `src/multi_agent_research_lab/evaluation/benchmark.py`
- `src/multi_agent_research_lab/evaluation/report.py`

Benchmark tối thiểu:

| Metric | Cách đo gợi ý |
|---|---|
| Latency | wall-clock time |
| Cost | token usage hoặc provider usage |
| Quality | rubric 0-10 do peer review |
| Citation coverage | số claims có source / tổng claims chính |
| Failure rate | số query fail / tổng query |

## Troubleshooting

### macOS: lỗi SSL certificate khi gọi API qua HTTPS (Tavily, OpenAI, ...)

Triệu chứng: khi implement `SearchClient` (hoặc bất kỳ HTTPS call nào) trên macOS, bạn có thể gặp lỗi kiểu:

```
ssl.SSLCertVerificationError: [SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed:
unable to get local issuer certificate
```

Nguyên nhân: Python cài từ python.org trên macOS **không dùng** certificate store của hệ điều hành, nên không tìm thấy CA bundle hợp lệ. Đây là lỗi môi trường, **không phải** do API key sai.

Cách khắc phục (chọn 1 trong 3):

1. **Chạy script cài certificate đi kèm Python** (nhanh nhất):

   ```bash
   /Applications/Python\ 3.12/Install\ Certificates.command
   ```

   (thay `3.12` bằng version Python của bạn)

2. **Dùng `certifi` trong code** — thêm `certifi` vào dependencies, rồi tạo SSL context khi gọi HTTPS:

   ```python
   import certifi
   import ssl
   from urllib.request import urlopen

   ssl_context = ssl.create_default_context(cafile=certifi.where())
   urlopen(request, timeout=timeout, context=ssl_context)
   ```

3. **Set biến môi trường** trỏ tới CA bundle của certifi (không cần đổi code):

   ```bash
   export SSL_CERT_FILE=$(python -m certifi)
   ```

## Exit ticket

Mỗi nhóm trả lời 2 câu:

1. Case nào nên dùng multi-agent? Vì sao?
Dùng multi-agent khi câu hỏi cần được trả lời có căn cứ, nghĩa là người đọc phải biết câu trả lời dựa trên nguồn nào, chứ không chỉ là một đoạn văn nghe hợp lý. Trong bài lab này, single-agent baseline về bản chất không thể làm được việc đó: nó chỉ có một lệnh gọi LLM duy nhất, không có bước đi tìm nguồn, nên không bao giờ biết "nguồn" của câu trả lời là gì để trích dẫn. Đây không phải là vấn đề có thể sửa bằng cách viết prompt khéo hơn, nó là giới hạn về cấu trúc. Số benchmark thật chạy được cho thấy đúng điều đó: multi-agent luôn đạt citation coverage 60-100%, còn single-agent thì cột đó luôn để trống vì không có gì để đo. Vậy nên bất cứ khi nào việc "trả lời đúng" quan trọng hơn "trả lời nhanh" — ví dụ viết báo cáo nghiên cứu, tổng hợp tài liệu, hay bất kỳ việc gì mà sau này có người sẽ hỏi "cái này bạn lấy từ đâu ra" — multi-agent là lựa chọn hợp lý, vì nó tách riêng bước tìm bằng chứng (Researcher) ra khỏi bước viết (Writer), nên câu trả lời cuối luôn bám theo nguồn thật thay vì chỉ là suy đoán của model.
2. Case nào không nên dùng multi-agent? Vì sao?
Ngược lại, với những câu hỏi ngắn, có một đáp án rõ ràng, không cần trích dẫn gì cả — ví dụ "tóm tắt đoạn văn này trong 3 câu" hay "giải thích khái niệm X là gì" — thì multi-agent chỉ tổ làm mọi thứ chậm và đắt hơn mà không thu lại được lợi ích gì. Benchmark thật cho thấy multi-agent chậm hơn khoảng gấp đôi (trung bình 15s so với 7s) và tốn gần gấp ba lần chi phí so với single-agent, vì nó phải gọi LLM 3-4 lần thay vì 1 lần. Nếu câu hỏi không cần trích dẫn, khoản chi phí thêm đó hoàn toàn lãng phí — mình đang trả tiền cho một quy trình "tìm nguồn → phân tích → viết" trong khi thực ra chẳng có nguồn nào đáng tìm cả. Đây đúng là điều mà bài lab muốn học viên tự rút ra: multi-agent không phải lúc nào cũng tốt hơn, nó chỉ đáng giá khi việc tách vai trò ra thực sự tạo ra thông tin/khả năng kiểm chứng mà một agent đơn lẻ không có — còn nếu không có nhu cầu đó thật sự, thêm agent chỉ là thêm chi phí điều phối mà không thêm giá trị.
