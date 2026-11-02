package org.jjikmuk.backend.domain.ocr

import jakarta.servlet.MultipartConfigElement
import org.springframework.beans.factory.annotation.Value
import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.core.annotation.Order
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.web.SecurityFilterChain
import org.springframework.security.web.access.intercept.AuthorizationFilter
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter
import org.jjikmuk.backend.global.config.JwtAuthenticationFilter
import org.jjikmuk.backend.domain.user.UserRepository

@Configuration
class OcrConfiguration {
    @Bean
    fun ocrProxy(@Value("\${ocr.proxy.base-url:}") baseUrl: String,
                 @Value("\${ocr.proxy.service-token:}") serviceToken: String) = OcrProxy(baseUrl, serviceToken)

    @Bean
    fun multipartConfigElement() = MultipartConfigElement("", 10L * 1024 * 1024, 10L * 1024 * 1024 + 65536, 0)

    @Bean
    @Order(1)
    fun ocrSecurity(http: HttpSecurity, @Value("\${ocr.proxy.enabled:false}") enabled: Boolean,
                    @Value("\${ocr.debug.enabled:false}") debugEnabled: Boolean,
                    @Value("\${ocr.debug.allowed-emails:}") debugEmails: String,
                    users: UserRepository,
                    jwtFilter: JwtAuthenticationFilter): SecurityFilterChain {
        val allowed = debugEmails.split(',').map { it.trim().lowercase() }.filter { it.isNotEmpty() }.toSet()
        // Reuse member JWT validation, including expiry, user lookup and tokenVersion.
        http.securityMatcher("/api/ocr", "/api/ocr/debug")
            .csrf { it.disable() }.formLogin { it.disable() }.httpBasic { it.disable() }
            .sessionManagement { it.sessionCreationPolicy(SessionCreationPolicy.STATELESS) }
            .exceptionHandling { it.authenticationEntryPoint { _, response, _ ->
                writeOcrError(response, 401, "AUTHENTICATION_REQUIRED", java.util.UUID.randomUUID().toString())
            } }
            .authorizeHttpRequests { it.anyRequest().authenticated() }
            .addFilterBefore(jwtFilter, UsernamePasswordAuthenticationFilter::class.java)
            .addFilterAfter(OcrGuard(enabled) { id ->
                debugEnabled && allowed.isNotEmpty() && users.findById(id).orElse(null)?.email?.lowercase() in allowed
            }, AuthorizationFilter::class.java)
        return http.build()
    }
}
