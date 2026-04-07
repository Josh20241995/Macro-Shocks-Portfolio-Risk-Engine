cmake_minimum_required(VERSION 3.20)
project(MacroShockRiskEngine VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# Compiler flags
if(MSVC)
    add_compile_options(/W4 /O2)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -O3 -march=native)
endif()

# ---------------------------------------------------------------------------
# Include directories
# ---------------------------------------------------------------------------
include_directories(${CMAKE_CURRENT_SOURCE_DIR}/include)

# ---------------------------------------------------------------------------
# Core library (used by tests and Python bindings)
# ---------------------------------------------------------------------------
add_library(msre_core STATIC
    src/scoring/fast_scorer.cpp
)
target_include_directories(msre_core PUBLIC include)

# ---------------------------------------------------------------------------
# Tests (using Catch2)
# ---------------------------------------------------------------------------
find_package(Catch2 3 QUIET)

if(Catch2_FOUND)
    add_executable(msre_tests
        tests/test_fast_scorer.cpp
    )
    target_link_libraries(msre_tests PRIVATE msre_core Catch2::Catch2WithMain)
    
    include(CTest)
    include(Catch)
    catch_discover_tests(msre_tests)
    
    message(STATUS "Catch2 found — tests enabled")
else()
    message(WARNING "Catch2 not found — C++ tests disabled. Install with: vcpkg install catch2 or conan install catch2")
endif()

# ---------------------------------------------------------------------------
# Python bindings (pybind11)
# ---------------------------------------------------------------------------
option(BUILD_PYTHON_BINDINGS "Build pybind11 Python bindings" ON)

if(BUILD_PYTHON_BINDINGS)
    find_package(pybind11 QUIET)
    if(pybind11_FOUND)
        pybind11_add_module(msre_fast_scorer
            bindings/fast_scorer_bindings.cpp
        )
        target_link_libraries(msre_fast_scorer PRIVATE msre_core)
        
        # Install to python/src for easy import
        install(TARGETS msre_fast_scorer
            LIBRARY DESTINATION ${CMAKE_CURRENT_SOURCE_DIR}/../python/src/macro_shock/risk_scoring
        )
        message(STATUS "pybind11 found — Python bindings enabled")
    else()
        message(WARNING "pybind11 not found — Python bindings disabled. Install with: pip install pybind11")
    endif()
endif()

# ---------------------------------------------------------------------------
# Build summary
# ---------------------------------------------------------------------------
message(STATUS "")
message(STATUS "=== Macro Shock Risk Engine C++ Build ===")
message(STATUS "  Compiler:        ${CMAKE_CXX_COMPILER_ID} ${CMAKE_CXX_COMPILER_VERSION}")
message(STATUS "  Build type:      ${CMAKE_BUILD_TYPE}")
message(STATUS "  Tests:           ${Catch2_FOUND}")
message(STATUS "  Python bindings: ${pybind11_FOUND}")
message(STATUS "")
