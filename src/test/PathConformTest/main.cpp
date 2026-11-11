//
// Copyright Contributors to the OpenRV Project
//
// SPDX-License-Identifier: Apache-2.0
//
// Unit tests for TwkUtil::pathIsURL and TwkUtil::pathConform: URLs, whatever
// their scheme, must reach the incoming-source-path event unchanged, while
// file paths are still normalized.
//
#define DOCTEST_CONFIG_IMPLEMENT_WITH_MAIN
#include <doctest/doctest.h>

#include <TwkUtil/PathConform.h>

using TwkUtil::pathConform;
using TwkUtil::pathIsURL;

TEST_CASE("pathIsURL accepts RFC 3986 schemes")
{
    CHECK(pathIsURL("http://example.com/movie.mov"));
    CHECK(pathIsURL("file:///mnt/shots/plate.exr"));
    CHECK(pathIsURL("bal:///shot/sh010"));

    // Digits, "+", "-" and "." after the first letter (e.g. asset manager entity references).
    CHECK(pathIsURL("ams2://shot/sh010"));
    CHECK(pathIsURL("my-ams://shot/sh010"));
    CHECK(pathIsURL("svn+ssh://host/repo"));
    CHECK(pathIsURL("com.example.ams://shot/sh010"));

    // Schemes are case-insensitive.
    CHECK(pathIsURL("HTTP://example.com/movie.mov"));
}

TEST_CASE("pathIsURL rejects paths and malformed schemes")
{
    CHECK_FALSE(pathIsURL(""));
    CHECK_FALSE(pathIsURL("/mnt/shots/plate.exr"));
    CHECK_FALSE(pathIsURL("relative/plate.exr"));
    CHECK_FALSE(pathIsURL("C:/shots/plate.exr"));
    CHECK_FALSE(pathIsURL("//server/share/plate.exr"));

    // A drive letter followed by a doubled slash is a path, not a one-letter scheme.
    CHECK_FALSE(pathIsURL("C://shots/plate.exr"));
    CHECK_FALSE(pathIsURL("c://shots/plate.exr"));

    // A scheme must start with a letter and must not be empty.
    CHECK_FALSE(pathIsURL("://shot/sh010"));
    CHECK_FALSE(pathIsURL("2ams://shot/sh010"));
    CHECK_FALSE(pathIsURL("-ams://shot/sh010"));

    // "://" must follow the scheme directly.
    CHECK_FALSE(pathIsURL("my ams://shot/sh010"));
    CHECK_FALSE(pathIsURL("/mnt/ams://shot/sh010"));
}

TEST_CASE("pathConform leaves URLs unchanged")
{
    CHECK(pathConform("my-ams://show//sh010") == "my-ams://show//sh010");
    CHECK(pathConform("ams2:///show/sh010") == "ams2:///show/sh010");
    CHECK(pathConform("file:///mnt//shots/plate.exr") == "file:///mnt//shots/plate.exr");
}

TEST_CASE("pathConform still normalizes paths")
{
#ifdef WIN32
    CHECK(pathConform("C:\\shots\\plate.exr") == "C:/shots/plate.exr");
    CHECK(pathConform("\\\\server\\share\\plate.exr") == "//server/share/plate.exr");
#else
    CHECK(pathConform("/mnt//shots//plate.exr") == "/mnt/shots/plate.exr");
#endif
}
