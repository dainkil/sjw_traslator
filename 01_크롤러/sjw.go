package main

import (
	"encoding/xml"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"regexp"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/PuerkitoBio/goquery"
)

// =====================================================================
const SaveDir = "./SJW_Corpus_Final"
const ProxyAddress = "http://YOUR_PROXY_ADDRESS"
// =====================================================================

type Article struct {
	ID       string `xml:"id,attr"`
	Original string `xml:"original"`
}

type Corpus struct {
	XMLName  xml.Name  `xml:"corpus"`
	Articles []Article `xml:"article"`
}

type Job struct {
	BaseCode string
	Month    int
	Day      int
	IsLeap   string // "A"(평달), "B"(윤달)
}

var (
	reSpace   = regexp.MustCompile(`[ \t]+`)
	reNewline = regexp.MustCompile(`\n+`)
	
	monthData = make(map[string][]Article)
	storageMu sync.Mutex
)

func cleanText(s string) string {
	s = reSpace.ReplaceAllString(s, " ")
	s = strings.ReplaceAll(s, " \n", "\n")
	s = strings.ReplaceAll(s, "\n ", "\n")
	s = reNewline.ReplaceAllString(s, "\n")
	return strings.TrimSpace(s)
}

func init() { rand.Seed(time.Now().UnixNano()) }

func loadExistingArticles(baseCode string) {
	storageMu.Lock()
	defer storageMu.Unlock()
	
	key := baseCode
	filename := fmt.Sprintf("%s/sjw_origin_%s.xml", SaveDir, baseCode)
	
	file, err := os.Open(filename)
	if err != nil {
		monthData[key] = []Article{}
		return
	}
	defer file.Close()
	
	var corpus Corpus
	byteValue, _ := io.ReadAll(file)
	xml.Unmarshal(byteValue, &corpus)
	monthData[key] = corpus.Articles
	
	if len(monthData[key]) > 0 {
		fmt.Printf("📂 [%s] 기존 %d건 로드 완료. 이어받기 재개!\n", baseCode, len(monthData[key]))
	}
}

func saveSingleArticle(baseCode string, art Article) {
	storageMu.Lock()
	defer storageMu.Unlock()

	key := baseCode
	monthData[key] = append(monthData[key], art)
	
	sort.Slice(monthData[key], func(i, j int) bool {
		return monthData[key][i].ID < monthData[key][j].ID
	})

	filename := fmt.Sprintf("%s/sjw_origin_%s.xml", SaveDir, baseCode)
	f, _ := os.Create(filename)
	defer f.Close()

	f.WriteString(xml.Header)
	enc := xml.NewEncoder(f)
	enc.Indent("", "    ")
	enc.Encode(Corpus{Articles: monthData[key]})
}

func fetchArticle(targetUrl string) (string, string) {
	proxyURL, _ := url.Parse(ProxyAddress)
	
	transport := &http.Transport{
		Proxy: http.ProxyURL(proxyURL),
		DisableKeepAlives: true, 
	}

	client := &http.Client{
		Transport: transport,
		Timeout:   20 * time.Second,
	}

	req, _ := http.NewRequest("GET", targetUrl, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64)")
	req.Header.Set("Connection", "close")

	resp, err := client.Do(req)
	if err != nil { return "ERROR", "" }
	defer resp.Body.Close()

	if resp.StatusCode == 404 || resp.StatusCode == 500 { return "NONE", "" }
	if resp.StatusCode != 200 { return "ERROR", "" }

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil { return "ERROR", "" }

	doc.Find("br").ReplaceWithHtml("\n")
	doc.Find("p").AppendHtml("\n")
	doc.Find("script, style, div.ins_nav, div.btn_area, div.print_area, span.url_copy").Remove()

	content := cleanText(doc.Find(".text_body, .ins_text, .view_font").Text())

	if content == "" || strings.Contains(content, "데이터가 없습니다") {
		return "NONE", ""
	}

	return "OK", content
}

func worker(id int, jobs <-chan Job, wg *sync.WaitGroup) {
	defer wg.Done()
	for job := range jobs {
		missCount := 0 
		
		for articleIdx := 1; articleIdx <= 50; articleIdx++ {
			
			sjwLeap := "0"
			if job.IsLeap == "B" {
				sjwLeap = "1"
			}
			
			sjwArticleNum := articleIdx * 100
			targetID := fmt.Sprintf("SJW-%s%02d%s%02d0-%05d", job.BaseCode, job.Month, sjwLeap, job.Day, sjwArticleNum)
			
			storageMu.Lock()
			key := job.BaseCode
			isDone := false
			for _, a := range monthData[key] {
				if a.ID == targetID { isDone = true; break }
			}
			storageMu.Unlock()
			if isDone { continue }

			url := "https://sjw.history.go.kr/id/" + targetID
			status, detail := "ERROR", ""
			
			for retry := 0; retry < 5; retry++ {
				status, detail = fetchArticle(url)
				if status != "ERROR" { break }
				fmt.Printf("🚨 [워커 %d] %s 지연. IP 로테이션 중... (%d/5)\n", id, targetID, retry+1)
				time.Sleep(1 * time.Second)
			}

			if status == "NONE" {
				missCount++
				if missCount >= 3 { break } 
				continue
			}

			if status == "OK" {
				missCount = 0 
				saveSingleArticle(job.BaseCode, Article{ID: targetID, Original: detail})
				fmt.Printf("    ✅ [워커 %d] %s 성공\n", id, targetID)
			}
			
			time.Sleep(time.Duration(rand.Intn(400)+400) * time.Millisecond)
		}
	}
}

func runCrawler(baseCode string, startM, startD int) {
	fmt.Printf("\n--- [%s] 수집 시작 (시작일: %d월 %d일) ---\n", baseCode, startM, startD)
	
	workerCount := 24
	jobs := make(chan Job, workerCount*2)
	var wg sync.WaitGroup

	for w := 1; w <= workerCount; w++ {
		wg.Add(1)
		go worker(w, jobs, &wg)
	}

	loadExistingArticles(baseCode)

	for m := startM; m <= 12; m++ {
		for _, leap := range []string{"A", "B"} {
			dStart := 1
			if m == startM && leap == "A" {
				dStart = startD
			}
			for d := dStart; d <= 31; d++ {
				jobs <- Job{BaseCode: baseCode, Month: m, Day: d, IsLeap: leap}
			}
		}
	}
	close(jobs)
	wg.Wait()
	fmt.Printf("\n💾 [%s] 수집 종료.\n", baseCode)
}

func main() {
	fmt.Println("🚀 승정원일기 국사편찬위원회(SJW) 원문 다이렉트 크롤링 시작")
	os.MkdirAll(SaveDir, 0755)

	// 1. 인조 (King Code: A) 1년 ~ 27년
	fmt.Println("\n▶️ [인조] 기록 수집 시작...")
	for y := 1; y <= 27; y++ {
		baseCode := fmt.Sprintf("A%02d", y)
		
		sMonth, sDay := 1, 1
		if y == 1 {
			// 인조 1년은 3월 12일부터 시작 (반정 이전 유령 페이지 스킵)
			sMonth, sDay = 3, 12
		}
		
		runCrawler(baseCode, sMonth, sDay)
	}

	// 2. 정조 (King Code: G) 0년(즉위년) ~ 24년
	fmt.Println("\n▶️ [정조] 기록 수집 시작...")
	for y := 0; y <= 24; y++ {
		baseCode := fmt.Sprintf("G%02d", y)
		runCrawler(baseCode, 1, 1) // 정조는 1월 1일부터 정상 수집
	}

	fmt.Println("🎉 인조, 정조 SJW 원문 수집 완료!")
}