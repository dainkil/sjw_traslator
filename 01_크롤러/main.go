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
// 사용자 환경에 맞춘 경로 및 설정
const SaveDir = `C:\Users\kevin\OneDrive\Desktop\sillok_crawler\SJW_Corpus_Special`
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

type Job struct {
	KingLetter string // P(인조), U(영조), Z(고종)
	Year       int
	Month      int
}

var (
	reSpace   = regexp.MustCompile(`[ \t]+`)
	reNewline = regexp.MustCompile(`\n+`)
	storageMu sync.Mutex
	// 연도별로 데이터를 따로 관리하기 위해 맵 구조 사용
	yearData = make(map[string][]Article)
)

func cleanText(s string) string {
	s = reSpace.ReplaceAllString(s, " ")
	s = strings.ReplaceAll(s, " \n", "\n")
	s = strings.ReplaceAll(s, "\n ", "\n")
	s = reNewline.ReplaceAllString(s, "\n")
	return strings.TrimSpace(s)
}

func init() { rand.Seed(time.Now().UnixNano()) }

func loadExistingArticles(king string, year int) {
	storageMu.Lock()
	defer storageMu.Unlock()
	key := fmt.Sprintf("%s_%d", king, year)
	filename := fmt.Sprintf("%s/sjw_%s_%02d.xml", SaveDir, king, year)
	
	file, err := os.Open(filename)
	if err != nil {
		yearData[key] = []Article{}
		return
	}
	defer file.Close()
	var corpus Corpus
	byteValue, _ := io.ReadAll(file)
	xml.Unmarshal(byteValue, &corpus)
	yearData[key] = corpus.Articles
}

func saveSingleArticle(king string, year int, art Article) {
	storageMu.Lock()
	defer storageMu.Unlock()

	key := fmt.Sprintf("%s_%d", king, year)
	yearData[key] = append(yearData[key], art)
	
	sort.Slice(yearData[key], func(i, j int) bool {
		return yearData[key][i].ID < yearData[key][j].ID
	})

	filename := fmt.Sprintf("%s/sjw_%s_%02d.xml", SaveDir, king, year)
	f, _ := os.Create(filename)
	defer f.Close()

	f.WriteString(xml.Header)
	enc := xml.NewEncoder(f)
	enc.Indent("", "    ")
	enc.Encode(Corpus{Articles: yearData[key]})
}

func fetchArticle(targetUrl string) (string, string, string) {
	proxyURL, _ := url.Parse(ProxyAddress)
	client := &http.Client{
		Transport: &http.Transport{Proxy: http.ProxyURL(proxyURL)},
		Timeout:   15 * time.Second,
	}

	req, _ := http.NewRequest("GET", targetUrl, nil)
	req.Header.Set("User-Agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36")

	resp, err := client.Do(req)
	if err != nil { return "ERROR", "", "" }
	defer resp.Body.Close()

	if resp.StatusCode == 404 { return "NONE", "", "" }
	if resp.StatusCode != 200 { return "ERROR", "", "" }

	doc, err := goquery.NewDocumentFromReader(resp.Body)
	if err != nil { return "ERROR", "", "" }

	doc.Find("br").ReplaceWithHtml("\n")
	doc.Find("script, style, .ins_nav, .btn_area, .print_area").Remove()

	// ITKC 번역본(U0/P0) 공통 셀렉터
	left := cleanText(doc.Find(".node_text_area.translation").Text())
	right := cleanText(doc.Find(".node_text_area.origin").Text())

	if left == "" && right == "" { return "NONE", "", "" }
	return "OK", left, right
}

func worker(id int, jobs <-chan Job, wg *sync.WaitGroup) {
	defer wg.Done()
	for job := range jobs {
		for day := 1; day <= 31; day++ {
			articleNum := 1
			for {
				// 패턴: ITKC_ST_{왕코드}0_A{연도}_{월}A_{일}A_{번호}
				// 입직상황(0001G)을 피하기 위해 00020부터 시작
				targetID := fmt.Sprintf("ITKC_ST_%s0_A%02d_%02dA_%02dA_%05d", 
					job.KingLetter, job.Year, job.Month, day, (articleNum+1)*10)
				
				storageMu.Lock()
				key := fmt.Sprintf("%s_%d", job.KingLetter, job.Year)
				isDone := false
				for _, a := range yearData[key] {
					if a.ID == targetID { isDone = true; break }
				}
				storageMu.Unlock()
				
				if isDone { articleNum++; continue }

				url := "https://db.itkc.or.kr/dir/item?itemId=ST&dataId=" + targetID
				status, trans, detail := "ERROR", "", ""
				
				for retry := 0; retry < 3; retry++ {
					status, trans, detail = fetchArticle(url)
					if status != "ERROR" { break }
					time.Sleep(1 * time.Second)
				}

				if status == "NONE" { break }

				if status == "OK" {
					saveSingleArticle(job.KingLetter, job.Year, Article{ID: targetID, Translation: trans, Original: detail})
					fmt.Printf("[워커 %d] %s 성공\n", id, targetID)
				}
				articleNum++
				time.Sleep(time.Duration(rand.Intn(300)+300) * time.Millisecond)
			}
		}
	}
}

func crawl(king string, year int, startM, endM int) {
	fmt.Printf("\n--- [%s] %d년 수집 시작 (%d월~%d월) ---\n", king, year, startM, endM)
	loadExistingArticles(king, year)
	
	jobs := make(chan Job, 8)
	var wg sync.WaitGroup

	for w := 1; w <= 8; w++ {
		wg.Add(1)
		go worker(w, jobs, &wg)
	}

	for m := startM; m <= endM; m++ {
		jobs <- Job{KingLetter: king, Year: year, Month: m}
	}
	close(jobs)
	wg.Wait()
}

func main() {
	os.MkdirAll(SaveDir, 0755)

	// 1. 병자호란: 인조(P) 14~15년
	crawl("P", 14, 12, 12)
	crawl("P", 15, 1, 1)

	// 2. 무신란: 영조(U) 4년
	crawl("U", 4, 3, 4)

	// 3. 갑신정변: 고종(Z) 21년
	crawl("Z", 21, 10, 10)

	fmt.Println("\n🎉 모든 역사적 구간 수집 완료.")
}
