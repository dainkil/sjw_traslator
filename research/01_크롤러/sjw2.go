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
const SaveDir = "./SJW_Corpus_History" // 저장 폴더명 변경
const ProxyAddress = "http://YOUR_PROXY_ADDRESS"
// =====================================================================

type Article struct {
	ID          string `xml:"id,attr"`
	Translation string `xml:"translation"`
	Original    string `xml:"original"`
}

type Corpus struct {
	XMLName  xml.Name  `xml:"corpus"`
	Articles []Article `xml:"article"`
}

// 📌 국사편찬위원회 패턴에 맞게 Job 구조체 변경
type Job struct {
	KingCode string // "A"(인조), "G"(정조)
	Year     int
	Month    int
	Day      int
	IsLeap   string // "0"(평달), "1"(윤달)
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
	
	filename := fmt.Sprintf("%s/sjw_%s.xml", SaveDir, baseCode)
	file, err := os.Open(filename)
	if err != nil {
		monthData[baseCode] = []Article{}
		return
	}
	defer file.Close()
	
	var corpus Corpus
	byteValue, _ := io.ReadAll(file)
	xml.Unmarshal(byteValue, &corpus)
	monthData[baseCode] = corpus.Articles
	
	if len(monthData[baseCode]) > 0 {
		fmt.Printf("📂 [%s] 기존 %d건 로드 완료. 이어받기 재개!\n", baseCode, len(monthData[baseCode]))
	}
}

func saveSingleArticle(baseCode string, art Article) {
	storageMu.Lock()
	defer storageMu.Unlock()

	monthData[baseCode] = append(monthData[baseCode], art)
	
	sort.Slice(monthData[baseCode], func(i, j int) bool {
		return monthData[baseCode][i].ID < monthData[baseCode][j].ID
	})

	filename := fmt.Sprintf("%s/sjw_%s.xml", SaveDir, baseCode)
	f, _ := os.Create(filename)
	defer f.Close()

	f.WriteString(xml.Header)
	enc := xml.NewEncoder(f)
	enc.Indent("", "    ")
	enc.Encode(Corpus{Articles: monthData[baseCode]})
}

func fetchArticle(targetUrl string) (string, string, string) {
	proxyURL, _ := url.Parse(ProxyAddress)
	client := &http.Client{
		Transport: &http.Transport{Proxy: http.ProxyURL(proxyURL)},
		Timeout:   15 * time.Second,
	}

	req, _ := http.NewRequest("GET", targetUrl, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

	resp, err := client.Do(req)
	if err != nil { return "ERROR", "", "" }
	defer resp.Body.Close()

	if resp.StatusCode == 404 || resp.StatusCode == 500 { return "NONE", "", "" }
	if resp.StatusCode != 200 { 
		// 403 에러 등이 뜨면 IP가 차단된 것입니다.
		fmt.Printf("\n🚨 서버 접근 거부 (상태 코드: %d)\n", resp.StatusCode)
		return "ERROR", "", "" 
	}

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil { return "ERROR", "", "" }

	// 원문 텍스트가 있는 div.view-text 추출 (스크린샷 구조 반영)
	// 번역문은 필요 없으므로 빈 문자열로 처리합니다.
	left := "" 
	right := cleanText(doc.Find("div.view-text").Text())

	// 원문 데이터가 없으면 없는 기사로 간주
	if right == "" {
		return "NONE", "", ""
	}

	return "OK", left, right
}

func worker(id int, jobs <-chan Job, wg *sync.WaitGroup) {
	defer wg.Done()
	for job := range jobs {
		missCount := 0 
		baseCode := fmt.Sprintf("%s%02d", job.KingCode, job.Year) // 예: A00, G00
		
		// 📌 기사 번호 1번(00100)부터 시작 (보통 1번 기사는 날씨/일자 정보)
		for articleNum := 1; articleNum <= 50; articleNum++ {
			// 📌 국사편찬위원회 URL 패턴에 맞춘 ID 생성 (기사번호 * 100 단위)
			targetID := fmt.Sprintf("SJW-%s%02d%02d%s%02d0-%05d", 
				job.KingCode, job.Year, job.Month, job.IsLeap, job.Day, articleNum*100)
			
			storageMu.Lock()
			isDone := false
			for _, a := range monthData[baseCode] {
				if a.ID == targetID { isDone = true; break }
			}
			storageMu.Unlock()
			if isDone { continue }

			// 📌 국사편찬위원회 도메인으로 변경
			url := "https://sjw.history.go.kr/id/" + targetID
			status, trans, detail := "ERROR", "", ""
			
			for retry := 0; retry < 5; retry++ {
				status, trans, detail = fetchArticle(url)
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
				saveSingleArticle(baseCode, Article{ID: targetID, Translation: trans, Original: detail})
				fmt.Printf("    ✅ [워커 %d] %s 성공\n", id, targetID)
			}
			
			time.Sleep(time.Duration(rand.Intn(400)+400) * time.Millisecond)
		}
	}
}

// 📌 baseCode 대신 왕 코드와 연도를 받아 처리하도록 수정
func runCrawler(kingCode string, year int, startM, endM int) {
	baseCode := fmt.Sprintf("%s%02d", kingCode, year)
	fmt.Printf("\n--- [%s] 수집 시작 (%d월 ~ %d월) ---\n", baseCode, startM, endM)
	
	workerCount := 12
	jobs := make(chan Job, workerCount*2)
	var wg sync.WaitGroup

	for w := 1; w <= workerCount; w++ {
		wg.Add(1)
		go worker(w, jobs, &wg)
	}

	loadExistingArticles(baseCode)

	for m := startM; m <= endM; m++ {
		for _, leap := range []string{"0", "1"} { // 0: 평달, 1: 윤달
			for d := 1; d <= 31; d++ {
				jobs <- Job{KingCode: kingCode, Year: year, Month: m, Day: d, IsLeap: leap}
			}
		}
	}
	close(jobs)
	wg.Wait()
	fmt.Printf("\n💾 [%s] 수집 종료.\n", baseCode)
}

func main() {
	fmt.Println("🚀 국사편찬위원회 승정원일기 무한 크롤링 시작")
	os.MkdirAll(SaveDir, 0755)

	// 1. 인조 (A) 0년 ~ 27년 구간 전체 (재위 기간 1623~1649)
	fmt.Println("\n▶️ [인조] 전체 기록 수집 시작...")
	for y := 21; y <= 27; y++ {
		runCrawler("A", y, 1, 12)
	}

	// 2. 정조 (G) 0년 ~ 24년 구간 전체 (재위 기간 1776~1800)
	fmt.Println("\n▶️ [정조] 전체 기록 수집 시작...")
	for y := 0; y <= 24; y++ {
		runCrawler("G", y, 1, 12)
	}

	fmt.Println("🎉 인조, 정조 가용 데이터 100% 수집 완료!")
}