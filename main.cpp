#include <algorithm>
#include <fstream>
#include <iostream>
#include <map>
#include <set>
#include <string>
#include <vector>

using namespace std;

enum class EventName {
  Thermal,
  Kinetic,
  Pressure,
  Electrical,
  Vibration,
  COUNT
};

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

  // 'head' is the most recent timestamp seen.
  // The 'tail' is implicitly (head - window + 1).
  int head[(int)EventName::COUNT];
  int window;

public:
  AverageCompute(int window) : window(window) {
    for (int i = 0; i < (int)EventName::COUNT; i++) {
      buckets[i].resize(window);
      totalSum[i] = 0;
      totalCount[i] = 0;
      head[i] = -1; // Initialize to -1 to handle T=0
    }
  }

  int normalize(int t) { return ((t % window) + window) % window; }

  void slide_window(int name, int new_head) {
    if (new_head <= head[name]) {
      return;
    }

    // Everything between the old head and the new head is now the "fresh"
    // space. We must erase these indices because they are the new front of the
    // window, which means their previous contents (from one window-cycle ago)
    // are now stale.
    int start_clear = head[name] + 1;
    int end_clear = new_head;

    // Safety: If we jump forward more than a full window,
    // we only need to clear the last 'window' worth of slots.
    if (end_clear - start_clear >= window) {
      start_clear = end_clear - window + 1;
    }

    for (int t = start_clear; t <= end_clear; t++) {
      int idx = normalize(t);
      Bucket &b = buckets[name][idx];

      // Subtract the "ghost" data from totals before wiping
      totalSum[name] -= b.sum;
      totalCount[name] -= b.count;
      b.reset();
    }

    head[name] = new_head;
  }

  void add_metric(int name, int timestamp, int value) {
    // 1. Ignore data that has already fallen off the tail
    if (head[name] != -1 && timestamp <= head[name] - window) {
      return;
    }

    slide_window(name, timestamp);

    // 3. Insert/Aggregate data
    // Since slide_window just cleared this slot (if it's new),
    // we can safely add to it.
    int idx = normalize(timestamp);
    Bucket &b = buckets[name][idx];

    b.timestamp = timestamp;
    b.sum += value;
    b.count += 1;

    totalSum[name] += value;
    totalCount[name] += 1;
  }

  double get_average(int name, int now) {
    slide_window(name, now);

    if (totalCount[name] == 0) {
      return 0.0;
    }
    return (double)totalSum[name] / (double)totalCount[name];
  }
};

// int main() {
//   ifstream cin("input");
//   if (!cin.is_open()) {
//     cerr << "Error: Could not open input file." << endl;
//     return 1;
//   }

//   int window;
//   if (!(cin >> window))
//     return 0;

//   AverageCompute ac(window);

//   int numOps;
//   if (!(cin >> numOps))
//     return 0;

//   string op;
//   while (numOps-- && (cin >> op)) {
//     if (op == "ADD") {
//       int name, timestamp, value;
//       cin >> name >> timestamp >> value;
//       ac.add_metric(name, timestamp, value);
//     } else if (op == "GET") {
//       int name, timestamp;
//       cin >> name >> timestamp;
//       cout << ac.get_average(name, timestamp) << endl;
//     }
//   }

//   return 0;
// }