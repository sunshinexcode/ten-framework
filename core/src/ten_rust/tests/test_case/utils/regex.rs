//
// Copyright © 2025 Agora
// This file is part of TEN Framework, an open source project.
// Licensed under the Apache License, Version 2.0, with certain conditions.
// Refer to the "LICENSE" file in the root directory for more information.
//
#[cfg(test)]
mod tests {
    use ten_rust::utils::regex::regex_full_match;

    #[test]
    fn test_regex_match_same_pattern_and_text() {
        let pattern = "extension_a";
        let text = "extension_a";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_substring_1() {
        let pattern = "extension_a";
        let text = "extension_a_b";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(!result);
    }

    #[test]
    fn test_regex_match_substring_2() {
        let pattern = "extension_a";
        let text = "b_extension_a_b";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(!result);
    }

    #[test]
    fn test_regex_match_all_1() {
        let pattern = ".*";
        let text = "extension_a";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_all_2() {
        let pattern = ".*";
        let text = "_extension_123";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_prefix_1() {
        let pattern = "extension_.*";
        let text = "extension_123";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_prefix_2() {
        let pattern = "extension_.*";
        let text = "aaa_extension_123";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(!result);
    }

    #[test]
    fn test_regex_match_suffix_1() {
        let pattern = ".*_asr_extension";
        let text = "aaa_asr_extension";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_suffix_2() {
        let pattern = ".*_asr_extension";
        let text = "aaa_asr_extension_123";
        let result = regex_full_match(pattern, text).unwrap();
        assert!(!result);
    }
}
