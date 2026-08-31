package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/PuerkitoBio/goquery"
)

const (
	proxy300   = "http://YOUR_PROXY_ADDRESS"
	evalFile   = "ablation5way/eval300_1925.json"
	outFile    = "ablation5way/sjw_raw_300.json"
	workers300 = 10
)

var reSpace300 = regexp.MustCompile(`[ \t]+`)
var reNL300    = regexp.MustCompile(`\n+`)

type evalData struct {
	IDs []string `json:"ids"`
}

func clean300(s string) string {
	s = reSpace300.ReplaceAllString(s, " ")
	s = strings.ReplaceAll(s, " \n", "\n")
	s = strings.ReplaceAll(s, "\n ", "\n")
	s = reNL300.ReplaceAllString(s, "\n")
	return strings.TrimSpace(s)
}

func fetch300(targetID string) (string, bool) {
	proxyURL, _ := url.Parse(proxy300)
	client := &http.Client{
		Transport: &http.Transport{
			Proxy:             http.ProxyURL(proxyURL),
			DisableKeepAlives: true,
		},
		Timeout: 20 * time.Second,
	}

	req, _ := http.NewRequest("GET", "https://sjw.history.go.kr/id/"+targetID, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
	req.Header.Set("Connection", "close")

	resp, err := client.Do(req)
	if err != nil {
		return "", false
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return "", false
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil {
		return "", false
	}

	text := clean300(doc.Find("div.title h3").Text())
	if text == "" || strings.Contains(text, "데이터가 없습니다") {
		return "", false
	}
	return text, true
}

func main() {
	// eval300_1925.json 읽기
	raw, err := os.ReadFile(evalFile)
	if err != nil {
		fmt.Println("eval 파일 읽기 실패:", err)
		os.Exit(1)
	}
	var eval evalData
	json.Unmarshal(raw, &eval)
	ids := eval.IDs
	fmt.Printf("대상: %d개\n", len(ids))

	// 기존 결과 로드 (이어받기)
	results := make(map[string]string)
	if b, err := os.ReadFile(outFile); err == nil {
		json.Unmarshal(b, &results)
		fmt.Printf("기존 완료: %d개\n", len(results))
	}

	// 남은 ID만 처리
	type job struct{ id string }
	jobs := make(chan job, workers300*2)
	var mu sync.Mutex
	var wg sync.WaitGroup

	for w := 0; w < workers300; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range jobs {
				var text string
				var ok bool
				for retry := 0; retry < 5; retry++ {
					text, ok = fetch300(j.id)
					if ok {
						break
					}
					fmt.Printf("  재시도 %s (%d/5)\n", j.id, retry+1)
					time.Sleep(time.Duration(1<<retry) * time.Second)
				}

				mu.Lock()
				if ok {
					results[j.id] = text
					fmt.Printf("  ✅ %s\n", j.id)
				} else {
					results[j.id] = ""
					fmt.Printf("  ❌ %s\n", j.id)
				}
				// 매번 저장 (중간 종료 대비)
				b, _ := json.MarshalIndent(results, "", "  ")
				os.WriteFile(outFile, b, 0644)
				mu.Unlock()

				time.Sleep(300 * time.Millisecond)
			}
		}()
	}

	sent := 0
	for _, id := range ids {
		mu.Lock()
		_, done := results[id]
		mu.Unlock()
		if done {
			continue
		}
		jobs <- job{id: id}
		sent++
	}
	close(jobs)
	wg.Wait()

	empty := 0
	for _, v := range results {
		if v == "" {
			empty++
		}
	}
	fmt.Printf("\n완료: %d개 저장 → %s  (빈 항목: %d개)\n", len(results), outFile, empty)
}
