// Compile SSM allowedPattern with Go, the engine used by SSM Agent.
// No modules, network, AWS credentials, or document execution.
package main

import (
	"encoding/json"
	"fmt"
	"os"
	"regexp"
)

type Sample struct {
	Value string
	Match bool
}
type Pattern struct {
	Name    string
	Pattern string
	Samples []Sample
}

func main() {
	var patterns []Pattern
	if err := json.NewDecoder(os.Stdin).Decode(&patterns); err != nil || len(patterns) == 0 {
		fmt.Println("INVALID_PATTERN_TEST_INPUT")
		os.Exit(1)
	}
	failed, samples := false, 0
	for _, item := range patterns {
		rx, err := regexp.Compile(item.Pattern)
		if err != nil {
			fmt.Printf("%s: %v\n", item.Name, err)
			failed = true
			continue
		}
		for i, sample := range item.Samples {
			samples++
			indices := rx.FindStringIndex(sample.Value)
			matched := indices != nil && indices[0] == 0 && indices[1] == len(sample.Value)
			if matched != sample.Match {
				fmt.Printf("%s: sample %d mismatch\n", item.Name, i)
				failed = true
			}
		}
	}
	if failed {
		os.Exit(1)
	}
	fmt.Printf("GO_SSM_PATTERNS_OK patterns=%d samples=%d\n", len(patterns), samples)
}
