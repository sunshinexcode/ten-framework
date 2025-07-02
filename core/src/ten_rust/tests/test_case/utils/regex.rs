//
// Copyright © 2025 Agora
// This file is part of TEN Framework, an open source project.
// Licensed under the Apache License, Version 2.0, with certain conditions.
// Refer to the "LICENSE" file in the root directory for more information.
//
#[cfg(test)]
mod tests {
    use ten_rust::utils::regex::{is_alphanumeric_characters, regex_match};

    #[test]
    fn test_is_alphanumeric_characters_1() {
        let text = "extension_a";
        let result = is_alphanumeric_characters(text);
        assert!(result);
    }

    #[test]
    fn test_is_alphanumeric_characters_2() {
        let text = ".*";
        let result = is_alphanumeric_characters(text);
        assert!(!result);
    }

    #[test]
    fn test_is_alphanumeric_characters_3() {
        let text = "extension_.*";
        let result = is_alphanumeric_characters(text);
        assert!(!result);
    }

    #[test]
    fn test_regex_match_substring_1() {
        let pattern = "^extension_a_.*$";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "b_extension_a_b";
        let result = regex_match(pattern, text).unwrap();
        assert!(!result);
    }

    #[test]
    fn test_regex_match_substring_2() {
        let pattern = "^extension_a_.*$";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "extension_a_b_c";
        let result = regex_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_all_1() {
        let pattern = ".*";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "extension_a";
        let result = regex_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_all_2() {
        let pattern = "*";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "extension_a";
        let result = regex_match(pattern, text);
        // * is not a valid regex pattern
        assert!(result.is_err());
    }

    #[test]
    fn test_regex_match_prefix_1() {
        let pattern = "^extension_.*$";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "extension_123";
        let result = regex_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_prefix_2() {
        let pattern = "^extension_.*$";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "aaa_extension_123";
        let result = regex_match(pattern, text).unwrap();
        assert!(!result);
    }

    #[test]
    fn test_regex_match_suffix_1() {
        let pattern = ".*_asr_extension";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "aaa_asr_extension";
        let result = regex_match(pattern, text).unwrap();
        assert!(result);
    }

    #[test]
    fn test_regex_match_suffix_2() {
        let pattern = ".*_asr_extension$";

        let is_alphanumeric = is_alphanumeric_characters(pattern);
        assert!(!is_alphanumeric);

        let text = "aaa_asr_extension_123";
        let result = regex_match(pattern, text).unwrap();
        assert!(!result);
    }
}
