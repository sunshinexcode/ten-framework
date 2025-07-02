//
// Copyright © 2025 Agora
// This file is part of TEN Framework, an open source project.
// Licensed under the Apache License, Version 2.0, with certain conditions.
// Refer to the "LICENSE" file in the root directory for more information.
//

use anyhow::Result;
use regex::Regex;

pub fn regex_full_match(pattern: &str, text: &str) -> Result<bool> {
    // Add anchors to the pattern to ensure it matches the entire text.
    let full_pattern = format!("^{pattern}$");

    let re = Regex::new(&full_pattern)?;
    Ok(re.is_match(text))
}
