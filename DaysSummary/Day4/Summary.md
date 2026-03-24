Day 4 Summary

Objective:
Build the first minimal token-level scheduler skeleton.

Implemented:
- FIFO waiting queue for incoming requests
- bounded active set (max_active_requests=3)
- explicit prefill phase for newly admitted requests
- shared decode loop that advances all active requests by one token per tick
- finish/removal logic that retires completed requests and admits waiting ones

Verified behavior from logs:
- The first 3 requests were admitted immediately, while later requests remained in the waiting queue
- Active requests advanced together in a shared decode loop with decode_batch_size=3
- As requests completed, decode_batch_size shrank from 3 to 2 to 1
- Waiting requests were admitted only after active slots freed up

Latency observations:
- Early admitted requests had low queue wait (~32–34 ms)
- Later admitted requests had much larger queue wait (~796–999 ms)
- Total latency for tail requests was dominated by queueing delay rather than just decode work
- Service time scaled roughly with the number of generated tokens

Conclusion:
The system no longer behaves like request -> full response.
It now behaves like request -> waiting queue -> admitted -> prefill -> shared iterative decode -> finish.

This establishes the control-plane foundation for continuous batching and later KV-cache-aware scheduling.