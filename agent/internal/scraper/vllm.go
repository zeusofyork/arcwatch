package scraper

import (
	"bufio"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"
)

type VLLMScraper struct {
	URL    string
	client *http.Client
}

func NewVLLMScraper(url string) *VLLMScraper {
	return &VLLMScraper{
		URL:    url,
		client: &http.Client{Timeout: 5 * time.Second},
	}
}

func (s *VLLMScraper) Scrape() (map[string]float64, error) {
	resp, err := s.client.Get(s.URL)
	if err != nil {
		return nil, fmt.Errorf("scrape %s: %w", s.URL, err)
	}
	defer resp.Body.Close()

	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("scrape %s: status %d", s.URL, resp.StatusCode)
	}

	return ParsePrometheusText(resp.Body)
}

// ParsePrometheusText extracts gauge metric values from Prometheus text format.
// Skips comments, histogram buckets (lines with {), and unparseable lines.
func ParsePrometheusText(r io.Reader) (map[string]float64, error) {
	result := make(map[string]float64)
	scanner := bufio.NewScanner(r)

	for scanner.Scan() {
		line := strings.TrimSpace(scanner.Text())
		if line == "" || strings.HasPrefix(line, "#") {
			continue
		}
		if strings.Contains(line, "{") {
			continue
		}
		parts := strings.Fields(line)
		if len(parts) < 2 {
			continue
		}
		val, err := strconv.ParseFloat(parts[1], 64)
		if err != nil {
			continue
		}
		result[parts[0]] = val
	}
	return result, scanner.Err()
}
