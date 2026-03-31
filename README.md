# Sliding Window Average Aggregator (C++)

A high-performance, $O(1)$ average-time telemetry aggregator. This implementation uses a **Circular Buffer** with a "Head/Tail" eviction model to ensure zero stale data with minimal computational overhead.

## 📖 Overview

This class is designed for systems where you need to track moving averages across multiple event types (e.g., Thermal, Kinetic, Electrical) over a fixed time window (e.g., 60 seconds). 

Instead of re-summing the entire window every time you need an average, this implementation maintains **running totals**. It uses a "Snowplow" logic to advance the window: as the `head` (current time) moves forward, it "scrubs" the indices it passes over, subtracting old data from the totals and clearing the buckets for new data.

## ✨ Key Features

- **Constant Time $O(1)$ Average:** Retrieval is a simple division of pre-maintained accumulators.
- **"Snowplow" Eviction:** Centralized, idempotent logic that wipes stale data only when time progresses.
- **Memory Efficient:** Uses a fixed-size array of vectors; no heap allocations after initialization.
- **Out-of-Order Safety:** Automatically ignores data falling behind the window while aggregating multiple samples for the same timestamp.
- **Metadata-Light:** Relies on the relationship between absolute time and array indices rather than constant metadata checks.

## 🚀 The Implementation

```cpp
#include <vector>

using namespace std;

enum class EventName { Thermal, Kinetic, Pressure, Electrical, Vibration, COUNT };

struct Bucket {
  int timestamp;
  long long sum;
  int count;

  Bucket() : timestamp(-1), sum(0), count(0) {}
  
  void reset() {
    this->timestamp = -1;
    this->sum = 0;
    this->count = 0;
  }
};

class AverageCompute {
private:
  vector<Bucket> buckets[(int)EventName::COUNT];
  long long totalSum[(int)EventName::COUNT];
  int totalCount[(int)EventName::COUNT];
  
  int head[(int)EventName::COUNT]; 
  int window;

public:
  AverageCompute(int window) : window(window) {
    for (int i = 0; i < (int)EventName::COUNT; i++) {
      buckets[i].resize(window);
      totalSum[i] = 0;
      totalCount[i] = 0;
      head[i] = -1; 
    }
  }

  int normalize(int t) {
    return ((t % window) + window) % window;
  }

  // Advances the window and scrubs the path (Snowplow Logic)
  void slide_window(int eIdx, int new_head) {
    if (new_head <= head[eIdx]) return;

    int start_clear = head[eIdx] + 1;
    int end_clear = new_head;

    if (end_clear - start_clear >= window) {
      start_clear = end_clear - window + 1;
    }

    for (int t = start_clear; t <= end_clear; t++) {
      int idx = normalize(t);
      Bucket &b = buckets[eIdx][idx];
      
      totalSum[eIdx] -= b.sum;
      totalCount[eIdx] -= b.count;
      b.reset();
    }
    
    head[eIdx] = new_head;
  }

  void add_metric(EventName name, int timestamp, int value) {
    int eIdx = (int)name;

    if (head[eIdx] != -1 && timestamp <= head[eIdx] - window) return;

    slide_window(eIdx, timestamp);

    int idx = normalize(timestamp);
    Bucket &b = buckets[eIdx][idx];
    
    b.timestamp = timestamp;
    b.sum += value;
    b.count += 1;
    
    totalSum[eIdx] += value;
    totalCount[eIdx] += 1;
  }

  double get_average(EventName name, int now) {
    int eIdx = (int)name;
    slide_window(eIdx, now);

    if (totalCount[eIdx] == 0) return 0.0;
    return (double)totalSum[eIdx] / (double)totalCount[eIdx];
  }
};


// 1. Create an aggregator with a 60-second window
AverageCompute tracker(60);

// 2. Add metrics (Value, Timestamp, Data)
tracker.add_metric(EventName::Thermal, 100, 25);
tracker.add_metric(EventName::Thermal, 100, 35); // Aggregates in the same second

// 3. Get average for the current window (O(1))
// This will automatically evict data older than T=41
double avg = tracker.get_average(EventName::Thermal, 101);