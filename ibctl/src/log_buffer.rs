//! In-memory log ring buffer for dashboard log queries.

use std::collections::VecDeque;
use std::fs::{create_dir_all, OpenOptions};
use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};

use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LogEntry {
    pub timestamp: String,
    pub level: String,
    pub message: String,
}

static LOG_BUFFER: OnceLock<Mutex<VecDeque<LogEntry>>> = OnceLock::new();
static LOG_FILE_PATH: OnceLock<PathBuf> = OnceLock::new();
const DEFAULT_CAPACITY: usize = 1000;

fn buffer() -> &'static Mutex<VecDeque<LogEntry>> {
    LOG_BUFFER.get_or_init(|| Mutex::new(VecDeque::with_capacity(DEFAULT_CAPACITY)))
}

pub fn push(entry: LogEntry) {
    append_to_file(&entry);
    if let Ok(mut guard) = buffer().lock() {
        if guard.len() >= DEFAULT_CAPACITY {
            guard.pop_front();
        }
        guard.push_back(entry);
    }
}

pub fn recent(limit: usize) -> Vec<LogEntry> {
    let limit = limit.max(1);
    if let Some(entries) = recent_from_file(limit) {
        return entries;
    }
    if let Ok(guard) = buffer().lock() {
        let len = guard.len();
        let start = len.saturating_sub(limit);
        guard.iter().skip(start).cloned().collect()
    } else {
        Vec::new()
    }
}

pub fn init_persistent_file(path: impl AsRef<Path>) -> std::io::Result<()> {
    let path = path.as_ref().to_path_buf();
    if let Some(parent) = path.parent() {
        create_dir_all(parent)?;
    }
    let _ = OpenOptions::new().create(true).append(true).open(&path)?;
    let _ = LOG_FILE_PATH.set(path);
    Ok(())
}

fn append_to_file(entry: &LogEntry) {
    let Some(path) = LOG_FILE_PATH.get() else {
        return;
    };
    let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) else {
        return;
    };
    let Ok(line) = serde_json::to_string(entry) else {
        return;
    };
    let _ = writeln!(file, "{}", line);
}

fn recent_from_file(limit: usize) -> Option<Vec<LogEntry>> {
    let path = LOG_FILE_PATH.get()?;
    let file = OpenOptions::new().read(true).open(path).ok()?;
    let reader = BufReader::new(file);
    let mut lines = VecDeque::with_capacity(limit);
    for line in reader.lines().map_while(Result::ok) {
        if let Ok(entry) = serde_json::from_str::<LogEntry>(&line) {
            if lines.len() >= limit {
                lines.pop_front();
            }
            lines.push_back(entry);
        }
    }
    Some(lines.into_iter().collect())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_recent_returns_latest_entries() {
        let entry_a = LogEntry {
            timestamp: "2026-04-10T00:00:00Z".to_string(),
            level: "INFO".to_string(),
            message: "a".to_string(),
        };
        let entry_b = LogEntry {
            timestamp: "2026-04-10T00:00:01Z".to_string(),
            level: "WARN".to_string(),
            message: "b".to_string(),
        };

        push(entry_a);
        push(entry_b);

        let recent = recent(1);
        assert_eq!(recent.len(), 1);
        assert_eq!(recent[0].message, "b");
    }
}
