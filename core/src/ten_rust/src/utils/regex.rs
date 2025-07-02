//
// Copyright © 2025 Agora
// This file is part of TEN Framework, an open source project.
// Licensed under the Apache License, Version 2.0, with certain conditions.
// Refer to the "LICENSE" file in the root directory for more information.
//

use anyhow::Result;
use once_cell::sync::Lazy;
use regex::Regex;

const ALPHANUMERIC_CHARACTERS_PATTERN: &str = r"^[A-Za-z_][A-Za-z0-9_]*$";

pub fn regex_match(pattern: &str, text: &str) -> Result<bool> {
    let re = Regex::new(pattern)?;
    Ok(re.is_match(text))
}

pub fn is_alphanumeric_characters(text: &str) -> bool {
    static ALPHANUMERIC_CHARACTERS_REGEX: Lazy<Regex> =
        Lazy::new(|| Regex::new(ALPHANUMERIC_CHARACTERS_PATTERN).unwrap());

    ALPHANUMERIC_CHARACTERS_REGEX.is_match(text)
}
