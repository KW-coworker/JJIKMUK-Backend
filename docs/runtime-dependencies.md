# Runtime dependency baseline

This records the security patch baseline previously present only in the operational build, so a future build from reviewed main does not silently downgrade it. It is not required to make Google OAuth registration work, nor a new framework-major migration.

| Dependency | Repository change | Reason / source |
|---|---|---|
| Spring Boot | 4.0.5 → 4.0.8 | Same 4.0 line patch baseline; [release notes](https://github.com/spring-projects/spring-boot/releases/tag/v4.0.8) include framework/dependency and runtime corrections. |
| Tomcat | BOM override 11.0.25 | Retain operational 11.0 patch baseline; review [Apache changelog](https://tomcat.apache.org/tomcat-11.0-doc/changelog.html), especially default-servlet session/URI handling. |
| Jackson 2 BOM | 2.21.7 | [Patch notes](https://github.com/FasterXML/jackson/wiki/Jackson-Release-2.21.7). Jackson 2 remains a JWT/runtime dependency. |
| Jackson 3 BOM | 3.1.7 | [Patch notes](https://github.com/FasterXML/jackson/wiki/Jackson-Release-3.1.7). Jackson 3 handles Spring request/response JSON. |
| Guava | explicit 33.7.2-jre | [GHSA-xxph-c9ww-hj94](https://github.com/google/guava/security/advisories/GHSA-xxph-c9ww-hj94), native deserialization memory allocation advisory, patched in 33.7.2. |

These pins reproduce the known operational dependency choice, not a claim that they are every package's newest release. Kotlin, Java 21, JJWT, Google API Client and application API/schema stay unchanged. Boot's BOM also changes transitive Spring/Hibernate/etc. versions; the full test suite and packaged JAR must be checked, not just these four version strings.

Package/version advisory matches are screening results, not proof of an exploitable application path. A clean advisory scan is not proof of security. See PR verification for resolved versions, current advisory results and test counts. Do not use runtime-only Gradle overrides at deployment time: all reviewed pins live here in source.
