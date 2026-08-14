//! Engine - Core inference logic with sequential and dataflow modes
//! Supports both native (tokio) and WASM (futures) targets
use anyhow::Result;
use std::sync::Arc;
use std::time::{Duration, Instant};

#[cfg(not(target_arch = "wasm32"))]
use tokio::sync::Semaphore;
#[cfg(not(target_arch = "wasm32"))]
use tokio::task::JoinSet;
#[cfg(not(target_arch = "wasm32"))]
use tokio::time::sleep as async_sleep;

#[cfg(target_arch = "wasm32")]
use futures::future::join_all;

use crate::contract::{BenchmarkConfig, BenchmarkResult, EngineMode, InferenceRequest, InferenceResponse};

/// Demo adapter that simulates inference with configurable latency
/// In production, this would call a real model (llama.cpp, ONNX, etc.)
pub struct DemoEngine {
    /// Base latency in microseconds
    base_latency_us: u64,
    /// Tokens per request (simulated)
    tokens_per_request: u32,
}

impl DemoEngine {
    pub fn new() -> Self {
        Self {
            base_latency_us: 1000, // 1ms base
            tokens_per_request: 3,
        }
    }

    /// Execute a single inference request
    pub async fn infer(&self, req: &InferenceRequest) -> Result<InferenceResponse> {
        // Simulate work
        self.sleep(Duration::from_micros(self.base_latency_us)).await;
        
        let output_tokens = self.tokens_per_request.min(req.max_tokens);
        let text = "x".repeat(output_tokens as usize);
        
        Ok(InferenceResponse {
            text,
            input_tokens: req.prompt.len() as u32 / 4,
            output_tokens,
            finish_reason: Some("stop".to_string()),
        })
    }

    /// Cross-platform async sleep
    async fn sleep(&self, dur: Duration) {
        #[cfg(not(target_arch = "wasm32"))]
        {
            async_sleep(dur).await;
        }
        #[cfg(target_arch = "wasm32")]
        {
            // WASM: use futures timer if available, otherwise busy wait
            #[cfg(feature = "wasm")]
            {
                use futures_timer::Delay;
                Delay::new(dur).await;
            }
            #[cfg(not(feature = "wasm"))]
            {
                // Fallback: busy wait (not ideal but works)
                let start = Instant::now();
                while start.elapsed() < dur {
                    // Yield to executor if available
                    futures::future::yield_now().await;
                }
            }
        }
    }

    /// Run benchmark in sequential mode (workers=1)
    pub async fn run_sequential(&self, config: &BenchmarkConfig) -> Result<BenchmarkResult> {
        let mut latencies = Vec::with_capacity(config.requests);
        let mut total_output_tokens = 0u64;
        
        let start = Instant::now();
        
        for _ in 0..config.requests {
            let req_start = Instant::now();
            let req = InferenceRequest {
                prompt: "benchmark prompt".to_string(),
                max_tokens: 64,
                temperature: None,
                top_p: None,
                stop: None,
            };
            
            let resp = self.infer(&req).await?;
            latencies.push(req_start.elapsed());
            total_output_tokens += resp.output_tokens as u64;
        }
        
        let wall = start.elapsed();
        let wall_ms = wall.as_millis() as u64;
        
        latencies.sort();
        let mean_latency_ms = latencies.iter().map(|d| d.as_millis() as f64).sum::<f64>() / latencies.len() as f64;
        let p95_idx = (latencies.len() as f64 * 0.95).ceil() as usize - 1;
        let p95_latency_ms = latencies[p95_idx.min(latencies.len() - 1)].as_millis() as f64;
        
        let tokens_per_second = if wall.as_secs_f64() > 0.0 {
            total_output_tokens as f64 / wall.as_secs_f64()
        } else {
            0.0
        };
        
        Ok(BenchmarkResult {
            adapter: "demo-adapter".to_string(),
            mode: EngineMode::Sequential,
            requests: config.requests,
            workers: 1,
            wall_ms,
            mean_latency_ms,
            p95_latency_ms,
            output_tokens: total_output_tokens as u32,
            tokens_per_second,
            repeats: config.repeats,
        })
    }

    /// Run benchmark in dataflow mode (worker pool)
    pub async fn run_dataflow(&self, config: &BenchmarkConfig) -> Result<BenchmarkResult> {
        #[cfg(not(target_arch = "wasm32"))]
        {
            self.run_dataflow_native(config).await
        }
        #[cfg(target_arch = "wasm32")]
        {
            self.run_dataflow_wasm(config).await
        }
    }

    #[cfg(not(target_arch = "wasm32"))]
    async fn run_dataflow_native(&self, config: &BenchmarkConfig) -> Result<BenchmarkResult> {
        let semaphore = Arc::new(Semaphore::new(config.workers));
        let mut latencies = Vec::with_capacity(config.requests);
        let total_output_tokens = Arc::new(std::sync::Mutex::new(0u64));
        
        let start = Instant::now();
        let mut join_set = JoinSet::new();
        
        for _ in 0..config.requests {
            let permit = semaphore.clone().acquire_owned().await?;
            let engine = self.clone();
            let tokens_ref = total_output_tokens.clone();
            
            join_set.spawn(async move {
                let req_start = Instant::now();
                let req = InferenceRequest {
                    prompt: "benchmark prompt".to_string(),
                    max_tokens: 64,
                    temperature: None,
                    top_p: None,
                    stop: None,
                };
                
                let resp = engine.infer(&req).await?;
                
                let latency = req_start.elapsed();
                *tokens_ref.lock().unwrap() += resp.output_tokens as u64;
                
                drop(permit);
                Ok::<_, anyhow::Error>((latency, resp))
            });
        }
        
        // Collect all results
        while let Some(res) = join_set.join_next().await {
            let (latency, _) = res??;
            latencies.push(latency);
        }
        
        let wall = start.elapsed();
        let wall_ms = wall.as_millis() as u64;
        let total_tokens = *total_output_tokens.lock().unwrap();
        
        latencies.sort();
        let mean_latency_ms = latencies.iter().map(|d| d.as_millis() as f64).sum::<f64>() / latencies.len() as f64;
        let p95_idx = (latencies.len() as f64 * 0.95).ceil() as usize - 1;
        let p95_latency_ms = latencies[p95_idx.min(latencies.len() - 1)].as_millis() as f64;
        
        let tokens_per_second = if wall.as_secs_f64() > 0.0 {
            total_tokens as f64 / wall.as_secs_f64()
        } else {
            0.0
        };
        
        Ok(BenchmarkResult {
            adapter: "demo-adapter".to_string(),
            mode: EngineMode::Dataflow,
            requests: config.requests,
            workers: config.workers,
            wall_ms,
            mean_latency_ms,
            p95_latency_ms,
            output_tokens: total_tokens as u32,
            tokens_per_second,
            repeats: config.repeats,
        })
    }

    #[cfg(target_arch = "wasm32")]
    async fn run_dataflow_wasm(&self, config: &BenchmarkConfig) -> Result<BenchmarkResult> {
        // WASM: no true concurrency yet, simulate by running sequentially
        // but report the dataflow mode metrics structure
        let mut latencies = Vec::with_capacity(config.requests);
        let mut total_output_tokens = 0u64;
        
        let start = Instant::now();
        
        // Run all requests sequentially (WASI doesn't have threads yet)
        for _ in 0..config.requests {
            let req_start = Instant::now();
            let req = InferenceRequest {
                prompt: "benchmark prompt".to_string(),
                max_tokens: 64,
                temperature: None,
                top_p: None,
                stop: None,
            };
            
            let resp = self.infer(&req).await?;
            latencies.push(req_start.elapsed());
            total_output_tokens += resp.output_tokens as u64;
        }
        
        let wall = start.elapsed();
        let wall_ms = wall.as_millis() as u64;
        
        latencies.sort();
        let mean_latency_ms = latencies.iter().map(|d| d.as_millis() as f64).sum::<f64>() / latencies.len() as f64;
        let p95_idx = (latencies.len() as f64 * 0.95).ceil() as usize - 1;
        let p95_latency_ms = latencies[p95_idx.min(latencies.len() - 1)].as_millis() as f64;
        
        let tokens_per_second = if wall.as_secs_f64() > 0.0 {
            total_output_tokens as f64 / wall.as_secs_f64()
        } else {
            0.0
        };
        
        Ok(BenchmarkResult {
            adapter: "demo-adapter".to_string(),
            mode: EngineMode::Dataflow,
            requests: config.requests,
            workers: config.workers,
            wall_ms,
            mean_latency_ms,
            p95_latency_ms,
            output_tokens: total_output_tokens as u32,
            tokens_per_second,
            repeats: config.repeats,
        })
    }
}

impl Clone for DemoEngine {
    fn clone(&self) -> Self {
        Self {
            base_latency_us: self.base_latency_us,
            tokens_per_request: self.tokens_per_request,
        }
    }
}