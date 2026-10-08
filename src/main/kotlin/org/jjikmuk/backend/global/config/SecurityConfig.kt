package org.jjikmuk.backend.global.config

import org.springframework.context.annotation.Bean
import org.springframework.context.annotation.Configuration
import org.springframework.security.config.annotation.web.builders.HttpSecurity
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity
import org.springframework.security.config.http.SessionCreationPolicy
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder
import org.springframework.security.web.SecurityFilterChain
import jakarta.servlet.http.HttpServletResponse
import org.jjikmuk.backend.global.exception.ApiErrorCode

@Configuration
@EnableWebSecurity
class SecurityConfig {

    // 💡 비밀번호 암호화를 담당할 BCrypt 빈 등록
    @Bean
    fun passwordEncoder(): BCryptPasswordEncoder {
        return BCryptPasswordEncoder()
    }

    @Bean
    fun filterChain(http: HttpSecurity, jwtFilter: JwtAuthenticationFilter): SecurityFilterChain {
        http
            .csrf { it.disable() }
            .formLogin { it.disable() }
            .httpBasic { it.disable() }
            .sessionManagement { it.sessionCreationPolicy(SessionCreationPolicy.STATELESS) }
            .exceptionHandling { exceptions ->
                exceptions.authenticationEntryPoint { _, response, _ ->
                    writeSecurityError(
                        response,
                        HttpServletResponse.SC_UNAUTHORIZED,
                        ApiErrorCode.AUTHENTICATION_REQUIRED,
                        "로그인이 필요합니다."
                    )
                }
                exceptions.accessDeniedHandler { _, response, _ ->
                    writeSecurityError(
                        response,
                        HttpServletResponse.SC_FORBIDDEN,
                        ApiErrorCode.ACCESS_DENIED,
                        "요청한 작업을 수행할 권한이 없습니다."
                    )
                }
            }
            .authorizeHttpRequests { auth ->
                auth
                    .requestMatchers(
                        "/api/auth/signup",
                        "/api/auth/login",
                        "/api/auth/google",
                        "/api/auth/email/**",
                        "/api/auth/password/reset",
                        "/api/auth/nicknames/availability"
                    ).permitAll()
                    .requestMatchers("/api/products/**").permitAll()
                    .anyRequest().authenticated()
            }
            // 💡 문지기(jwtFilter)를 시큐리티 기본 인증 과정보다 앞서 배치!
            .addFilterBefore(jwtFilter, org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter::class.java)

        return http.build()
    }

    private fun writeSecurityError(
        response: HttpServletResponse,
        status: Int,
        code: String,
        message: String
    ) {
        response.status = status
        response.characterEncoding = Charsets.UTF_8.name()
        response.contentType = "application/json"
        response.writer.write(
            """{"status":$status,"code":"$code","message":"$message"}"""
        )
    }
}
