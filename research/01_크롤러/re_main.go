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

// =====================================================================
const JsonFile = "error_96_articles.json" // 파이썬이 뽑아준 오류 목록
const OutFile = "repaired_raw_96.json"   // 최종 JSON 결과물
const ProxyAddress = "http://YOUR_PROXY_ADDRESS"
// =====================================================================

type Article struct {
	ID          string `json:"article_id"`
	Translation string `json:"translation"`
	Original    string `json:"original"`
}

var (
	reSpace   = regexp.MustCompile(`[ \t]+`)
	reNewline = regexp.MustCompile(`\n+`)
	storageMu sync.Mutex
	repaired  []Article
)

func cleanText(s string) string {
	s = reSpace.ReplaceAllString(s, " ")
	s = strings.ReplaceAll(s, " \n", "\n")
	s = strings.ReplaceAll(s, "\n ", "\n")
	s = reNewline.ReplaceAllString(s, "\n")
	return strings.TrimSpace(s)
}

func fetchByID(id string) (string, string, string) {
	// 💡 주소 생성 오류 해결: ID를 그대로 주소 뒤에 붙임
	targetUrl := "https://sillok.history.go.kr/id/" + id
	
	proxyURL, _ := url.Parse(ProxyAddress)
	client := &http.Client{
		Transport: &http.Transport{Proxy: http.ProxyURL(proxyURL)},
		Timeout:   15 * time.Second,
	}

	req, _ := http.NewRequest("GET", targetUrl, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0")

	resp, err := client.Do(req)
	if err != nil || resp.StatusCode != 200 { return "ERROR", "", "" }
	defer resp.Body.Close()

	doc, _ := goquery.NewDocumentFromReader(resp.Body)
	
	// 💡 노이즈 방지: <br>을 줄바꿈으로 확실히 치환
	doc.Find("br").ReplaceWithHtml("\n")
	doc.Find("script, style, .ins_nav, .btn_area").Remove()

	trans := cleanText(doc.Find("div.view-item.left").Text())
	orig := cleanText(doc.Find("div.view-item.right").Text())

	return "OK", trans, orig
}

func main() {
	// 1. JSON 읽기
	file, _ := os.ReadFile(JsonFile)
	var errorList map[string]interface{}
	json.Unmarshal(file, &errorList)

	fmt.Printf("🚀 총 %d개의 기사 핀셋 수집 시작...\n", len(errorList))

	var wg sync.WaitGroup
	jobs := make(chan string, len(errorList))

	for w := 1; w <= 5; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for id := range jobs {
				status, trans, orig := fetchByID(id)
				if status == "OK" {
					storageMu.Lock()
					repaired = append(repaired, Article{ID: id, Translation: trans, Original: orig})
					storageMu.Unlock()
					fmt.Printf("  ✅ %s 수집 완료\n", id)
				}
				time.Sleep(500 * time.Millisecond)
			}
		}()
	}

	for id := range errorList { jobs <- id }
	close(jobs)
	wg.Wait()

	// 2. JSON 저장
	outFile, _ := os.Create(OutFile)
	enc := json.NewEncoder(outFile)
	enc.SetIndent("", "  ")
	enc.Encode(repaired)
	fmt.Println("🎉 모든 기사 재수집 및 JSON 저장 완료!")
}